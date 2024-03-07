import asyncio
from contextlib import suppress
import pytest
from unittest.mock import MagicMock, AsyncMock
from wandb.sdk.launch.agent.job_status_tracker import JobAndRunStatusTracker
from wandb.sdk.launch.agent.run_queue_item_file_saver import RunQueueItemFileSaver

from wandb.sdk.launch.agent2.agent import LaunchAgent2
from wandb.sdk.launch.agent2.controller import LegacyResources
from wandb.sdk.launch.agent2.jobset import JobSet
from wandb.sdk.launch.builder.abstract import AbstractBuilder
from wandb.sdk.launch.environment.abstract import AbstractEnvironment
from wandb.sdk.launch.registry.abstract import AbstractRegistry
from wandb.sdk.launch.runner.abstract import AbstractRunner

class AsyncMock2(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)
    
    def __hash__(self):
        return id(self)
    
@pytest.fixture
def fresh_agent():
    def reset():
        LaunchAgent2._instance = None
        LaunchAgent2._initialized = False
        LaunchAgent2._controller_impls = {}
        
    reset()
    yield
    reset()
    
@pytest.fixture
def common_setup(mocker):
    mocker.api = MagicMock()
    
    mocker.api.jobset_introspection = MagicMock(return_value={"JobSetDiffType": {"name": "JobSetDiff"}})
    mock_agent_response = {"name": "test-name", "stopPolling": False}
    mocker.api.get_launch_agent = MagicMock(return_value=mock_agent_response)
    mocker.api.fail_run_queue_item = MagicMock(side_effect=KeyboardInterrupt)
    
    mocker.termlog = MagicMock()
    mocker.termwarn = MagicMock()
    mocker.termerror = MagicMock()
    mocker.wandb_init = MagicMock()
    mocker.patch("wandb.termlog", mocker.termlog)
    mocker.patch("wandb.termwarn", mocker.termwarn)
    mocker.patch("wandb.termerror", mocker.termerror)
    mocker.patch("wandb.init", mocker.wandb_init)

    mocker.status = MagicMock()
    mocker.status.state = "running"
    mocker.run = MagicMock()

    mocker.run.get_status = AsyncMock(return_value=mocker.status)
    mocker.runner = MagicMock()

    async def _mock_runner_run(*args, **kwargs):
        return mocker.run

    mocker.runner.run = _mock_runner_run
    mocker.patch(
        "wandb.sdk.launch.agent.agent.loader.runner_from_config",
        return_value=mocker.runner,
    )
    
def test_agent_controller_registry(fresh_agent):
    test_controller = MagicMock()
    LaunchAgent2.register_controller_impl("test-exists", test_controller)
    
    assert LaunchAgent2.get_controller_for_jobset("test-exists") is test_controller
    with pytest.raises(ValueError):
        LaunchAgent2.get_controller_for_jobset("test-nothing")
        
def test_agent_is_singleton(mocker, common_setup, fresh_agent):
    config = {
        "entity": "test-entity",
        "project": "test-project",
        "queues": [],
    }
    
    agent1 = LaunchAgent2(api=mocker.api, config=config)
    agent2 = LaunchAgent2(api=mocker.api, config=config)
    
    assert agent1 is agent2
    assert isinstance(agent1, LaunchAgent2)

@pytest.mark.asyncio
async def test_agent_loop(mocker, common_setup, fresh_agent):
    mock_controller = AsyncMock(return_value=None)
    LaunchAgent2.register_controller_impl("test-resource", mock_controller)
   
    loader = MagicMock()
    loader.environment_from_config = MagicMock(return_value=MagicMock(spec=AbstractEnvironment))
    loader.registry_from_config = MagicMock(return_value=MagicMock(spec=AbstractRegistry))
    loader.builder_from_config = MagicMock(return_value=MagicMock(spec=AbstractBuilder))
    loader.runner_from_config = MagicMock(return_value=MagicMock(spec=AbstractRunner))
    mocker.patch("wandb.sdk.launch.agent2.agent.loader", loader)
    
    rqi_filesaver = MagicMock(spec=RunQueueItemFileSaver)
    mocker.patch("wandb.sdk.launch.agent2.agent.RunQueueItemFileSaver", rqi_filesaver)
    
    status_tracker = MagicMock(spec=JobAndRunStatusTracker)
    mocker.patch("wandb.sdk.launch.agent2.agent.JobAndRunStatusTracker", status_tracker)
    
    legacy_resources = MagicMock(spec=LegacyResources)
    mocker.patch("wandb.sdk.launch.agent2.agent.LegacyResources", legacy_resources)
    
    loop = asyncio.get_event_loop()
    
    jobset = MagicMock(spec=JobSet)
    jobset.start_sync_loop = MagicMock()
    jobset.wait_for_done = loop.create_future()
    jobset.wait_for_done.set_result(True)
    jobset.ready = AsyncMock(return_value=None)
    
    jobset.metadata = {"@id": "test-id", "@name": "test-query", "@target_resource": "test-resource"}
    create_jobset = MagicMock(return_value=jobset)
    mocker.patch("wandb.sdk.launch.agent2.agent.create_jobset", create_jobset)
    
    config = {
        "entity": "test-entity",
        "project": "test-project",
        "queues": ["test-queue"],
    }
    
    agent = LaunchAgent2(api=mocker.api, config=config)
    loop_task = loop.create_task(agent.loop())
    await asyncio.sleep(2)
    loop_task.cancel()
    
    with suppress(asyncio.CancelledError):
        await loop_task
    