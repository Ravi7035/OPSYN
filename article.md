# I Gave My Incident Agent a Memory of What Went Wrong

Most incident automation has the attention span of a shell script. It can inspect the system in front of it, but the moment the incident closes, the hard-won reasoning that led to the fix disappears into a ticket, a chat thread, or somebody's memory.

I built OPSYN around a narrower idea: an incident agent should remember how a previous incident was investigated, including the bad turns, and treat that memory as evidence—not as a command to repeat. That distinction turned out to be the entire project.

![OPSYN landing view showing repeated incidents, an organizational-memory event, and a subsequent verified recovery](C:/Users/ravim/OneDrive/Pictures/Screenshots/Screenshot%202026-09-29%20124531.png)

*The opening view frames the problem chronologically: repeated symptoms become retained experience, then a later incident can use it and still verify recovery.*

## The system I built

OPSYN is an incident-response service for a payment API. A React command center talks to a FastAPI backend. The backend owns an `IncidentResponseAgent`, a constrained tool layer, a reasoning-model interface, an incident store, and a Hindsight-backed memory service. The agent runs one loop:

```text
Observe -> Recall -> Hypothesize -> Investigate -> Act -> Verify -> Learn -> Remember
```

The loop is deliberately more important than the model. The agent first collects health, metrics, state, and logs. It then asks [Hindsight's agent memory repository](https://github.com/vectorize-io/hindsight) for relevant past experience, ranks hypotheses using both inputs, and chooses a bounded next step. If it acts, it observes the system again. Only then does it record the outcome for the next incident.

![OPSYN overview with the Observe, Remember, Reason, Act, Verify, and Learn loop](C:/Users/ravim/OneDrive/Pictures/Screenshots/Screenshot%202026-09-29%20124554.png)

*This overview shows the loop as an operator sees it. “Verify” is a first-class stage, not a success message displayed after an action.*

The simulator in this repository exposes eight failure modes with distinct observable signatures: exhausted database connections, a bad deployment, a memory leak, Redis failure, dependency timeout, traffic spike, cache stampede, and disk exhaustion. More importantly, it has actions that can do nothing. `clear_db_connections` resolves a saturated pool; issuing it during a bad deployment returns “no significant change observed.” That sounds obvious, but it gives the agent a chance to learn from a wrong action instead of quietly overwriting it with a clean success story.

## Memory is useful only when it can be contradicted

The tempting implementation was simple: retrieve an old incident and tell the model to follow the recorded fix. I rejected that approach after working through the misleading-memory case. Incident response is exactly where it fails: similar metrics often have different causes, and stale incident history can be dangerously persuasive.

Instead, I made Hindsight a source of historical evidence alongside live observations. A recalled DB-pool incident can support the DB hypothesis when connections are 100/100 and latency is 900 ms. It cannot make a healthy database look exhausted when a deployment just changed and the error rate jumped.

The important boundary appears in the agent's tool layer. The simulator has hidden state so tests can configure a fault, but the agent is never allowed to read it:

```python
def get_snapshot(self) -> dict[str, object]:
    return {
        "health": self.get_health(),
        "metrics": self.get_metrics(),
        "state": self.get_state(),
        "logs": self._logs[-20:],
    }
```

`active_fault`, the expected remediation, and root-cause labels remain internal. The agent has to infer the cause from the same sort of inputs an operator would inspect. The test suite also audits retained and recalled text for forbidden hidden-state strings. That mattered to me: without it, an evaluation can look impressive simply because the answer leaked through a convenient field.

![Recorded OPSYN incidents showing a DB-pool resolution and a separate deployment rollback](C:/Users/ravim/OneDrive/Pictures/Screenshots/Screenshot%202026-09-29%20124610.png)

*The incident list makes the distinction visible: “Clear DB connections” and “Rollback deployment” are separate, verified outcomes rather than one generic recovery path.*

I also made current evidence outweigh memory in the deterministic reasoning model. Historical success adds support. A historical failure subtracts support. Current signals can reject a hypothesis outright. The relevant test seeds a memory saying that clearing DB connections fixed a prior incident, then injects a bad deployment. The correct result is a rejected DB hypothesis and `rollback_deployment`, not a confident replay of the old command.

That is the opinionated part of the design: memory should make an agent less amnesiac, not less skeptical. The [Hindsight documentation for durable agent memory](https://hindsight.vectorize.io/) is useful here because the problem is not merely retrieval quality. It is deciding what a retrieved account is allowed to influence.

## I stored an experience, not a resolution label

The second design decision followed from the first. A record like `db_pool_exhaustion -> clear_db_connections` is too thin to be useful and too easy to misuse. It contains neither the conditions that justified the action nor the failed alternatives worth avoiding.

For every handled incident, OPSYN retains observed evidence, hypotheses, investigation steps, attempted actions, verification metrics, and a lesson. The Hindsight integration owns the provider boundary and sends a structured incident representation, rather than letting unrelated services call the SDK:

```python
response = await self._client.aretain(
    bank_id=self._bank_id,
    content=incident.to_memory_text(),
    context=incident.to_memory_context(),
    metadata=incident.to_memory_metadata(),
    document_id=incident.incident_id,
    tags=["sre", "incident", incident.service, incident.environment],
)
```

That full trace is why a later recall can say more than “try restart service.” It can show that the previous incident had degraded cache health, high database load, the actions tried, and the observed recovery. It can also carry the fact that a Redis restart made no difference before the correct DB action succeeded.

![OPSYN organizational-memory cards showing incident evidence, a successful response, and the resulting lesson](C:/Users/ravim/OneDrive/Pictures/Screenshots/Screenshot%202026-09-29%20124622.png)

*The memory view shows the payload I want to preserve: the incident context, the successful remediation, and a concrete lesson tied to observed metrics.*

Failed actions are not embarrassing telemetry to discard. They are negative evidence. During an incident, OPSYN will not blindly retry a failed action without new evidence. Across incidents, a recalled failure gets weaker negative weight than a failure observed in the current incident; live data still wins. That asymmetry is deliberate. A past failure is suggestive. A command that just failed against the system in front of you is much stronger information.

## What happens on two similar-looking incidents

Consider the DB pool case. The agent observes a degraded service, `db_connections=100/100`, database latency around 900 ms, and a 25.0% 5xx rate. It selects the DB-pool hypothesis, runs `clear_db_connections`, and then fetches metrics again. In the simulator, the before/after result is concrete: 5xx falls from 25.0% to 0.2% and the health status becomes `healthy`. Recovery is not inferred from the action's return value; it requires those observations.

The verification code is intentionally boring:

```python
resolved = bool(
    not no_change
    and health_status == "healthy"
    and after_5xx < 1.0
)
```

I prefer this to “the API call did not throw.” Action APIs routinely report success for work that did not restore service. A restart may complete. A cache flush may be accepted. Neither means the incident is over.

On a later incident, Hindsight can recall the earlier DB experience before the agent scores its hypotheses. In the repository's learning experiment, a DB incident is retained and a later cache-stampede incident recalls it. The agent still selects `restart_service`, because degraded cache signals, high CPU, and cache-stampede log signatures explain the current state better than an isolated DB-pool failure.

![Memory-aware OPSYN flow contrasting telemetry-only handling with comparison, verification, and retention](C:/Users/ravim/OneDrive/Pictures/Screenshots/Screenshot%202026-09-29%20124636.png)

*The right-hand path is the architectural claim in one screen: current telemetry is combined with prior experience, then the response is verified and the new experience is retained.*

The checked-in deterministic evaluation reports show all eight defined fault scenarios resolving in both cold and experienced runs. They do **not** show a faster or more accurate system when memory is present; the outcome is the same. This was an important limitation, not a footnote. What the reports show is that experienced runs recall prior incidents and retain complete traces, while the dedicated misleading-memory test confirms that a prior DB success does not force the DB action during a bad deployment. I think that is the honest result to report. Reuse and safe rejection are demonstrated; broad operational gains require production evidence.

## What I learned building it

1. **Retrieval is not a decision.** Retrieved memory needs a clear evidentiary role, provenance, and a way to lose to fresher observations. This is the useful distinction behind [Vectorize's explanation of agent memory](https://vectorize.io/what-is-agent-memory): retaining context is only the beginning of a reliable loop.

2. **Keep the evaluator's truth out of the agent's context.** Fault injectors and expected outcomes are useful test fixtures, not observations. I treated them as secrets and tested the boundary, because otherwise it is too easy to mistake data leakage for reasoning.

3. **Record failures with the same care as successes.** The failed Redis restart in an incident trace is often more reusable than a vague “resolved” status. It tells the next investigation what was tried, under what signals, and what did not change.

4. **Verification deserves its own interface and data model.** An action result is a statement about execution; a before/after metric comparison is evidence about recovery. Collapsing them hides incidents that are still in progress.

5. **Bound the agent before making it clever.** OPSYN limits investigation and remediation actions. A bounded loop makes its failures inspectable, keeps escalation possible, and prevents memory from turning into an excuse for unbounded autonomy.

I did not set out to build a system that “knows” incident response. I wanted one that could carry forward the useful parts of a real investigation: what it saw, what it considered, what it tried, what failed, and what evidence proved recovery. Hindsight gives that experience somewhere durable to live. The rest of the design exists to make sure the next incident can benefit from it without becoming captive to it.
