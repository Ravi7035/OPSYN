"""Evaluation scenarios: the simulator fault taxonomy, unchanged.

The evaluator (not the agent) uses these names as ground truth to configure
each scenario. Nothing here is ever passed into the agent.
"""

from app.models.incident import Incident, IncidentSource
from app.services.payment_simulator import FAULTS

SCENARIOS: list[str] = list(FAULTS)

# Second incident where DB evidence is relevant but the fault differs.
# Used by the cross-incident learning experiment (§16).
DB_RELEVANT_SCENARIO = "cache_stampede"

# Current incident for the misleading-memory experiment (§17): DB metrics
# are healthy while deployment evidence points at a bad release.
MISLEADING_CURRENT_SCENARIO = "bad_deployment"
MISLEADING_HISTORY_SCENARIO = "db_pool_exhaustion"


def new_scenario_incident(
    mode: str,
    seq: int,
    service: str = "payment-api",
) -> Incident:
    """Build a neutral incident shell for one evaluation run.

    The incident carries no fault identifier: no ``fault_type`` and an ID
    that cannot leak which scenario was injected. The agent must infer
    everything from observations.
    """
    return Incident(
        incident_id=f"eval-{mode}-{seq:02d}",
        service=service,
        environment="production",
        source=IncidentSource.SIMULATOR,
        fault_type=None,
        symptoms=[f"OPSYN {mode} evaluation"],
    )
