"""A finite waiter with short leases; no provider or schema side effects."""
import argparse
import json
from datetime import datetime
from agent_os.application.services.communication_wait import CommunicationWait
from agent_os.domain.entities.communication import Caller
from agent_os.infrastructure.composition.communication_runtime import prepared_runtime
from agent_os.infrastructure.config import LocalPlatformSettings

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--settings', required=True)
    parser.add_argument('--message', required=True)
    parser.add_argument('--clock', required=True)
    args = parser.parse_args()
    with prepared_runtime(LocalPlatformSettings(**json.loads(args.settings)), 'w') as (_, service):
        service.clock = lambda: datetime.fromisoformat(args.clock)
        result = CommunicationWait(service, service.coordination).wait(Caller('w','a'), args.message,
            condition='final', timeout=5, poll_interval=.02, heartbeat_interval=.05, lease_seconds=.2)
        print(json.dumps(result))
