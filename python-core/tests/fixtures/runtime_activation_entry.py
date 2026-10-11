"""Explicit test composition in the child, never selected by a production field."""
import os
from agent_os.communication_activation import main
from test_claude_registered_session_activation import _sdk_runtime, _sdk_result
from fixtures.fake_runtime_receiver import receive


def configure(platform):
    platform.claude_agent_sdk_runtime_loader = lambda: _sdk_runtime(compatible=True)
    def runner(*args, **kwargs):
        receive(kwargs["prompt"], os.environ["BEACON_TEST_TRACE"], os.environ["BEACON_TEST_GATE"])
        return _sdk_result(final_response="synthetic SDK final")
    platform.claude_agent_sdk_runner = runner


if __name__ == "__main__":
    raise SystemExit(main(configure=configure))
