from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import asyncio

app = FastAPI()

global_state = {"is_paused": False, "instrumentor": None, "events": []}
ws_clients = []


@app.websocket("/ws")
async def ws(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()
    except:
        ws_clients.remove(websocket)


async def broadcast(data: dict):
    for client in ws_clients:
        try:
            await client.send_json(data)
        except:
            pass


@app.post("/api/pause")
async def pause():
    global_state["is_paused"] = True
    if global_state["instrumentor"]:
        global_state["instrumentor"].emitter.is_paused = True
    await broadcast({"type": "pause"})
    return {"status": "paused"}


@app.post("/api/resume")
async def resume():
    global_state["is_paused"] = False
    if global_state["instrumentor"]:
        global_state["instrumentor"].emitter.is_paused = False
    await broadcast({"type": "resume"})
    return {"status": "resumed"}


@app.post("/api/modify_and_replay")
async def modify_and_replay(fork_at_step: int, tool_output: str):
    from agent_obs.replay import ReplayEngine
    engine = ReplayEngine(global_state["instrumentor"])
    fork_id = await engine.fork_and_rerun(fork_at_step, tool_output)
    await broadcast({"type": "fork_created", "fork_id": fork_id, "fork_at_step": fork_at_step})
    return {"fork_id": fork_id}


@app.post("/api/run_agent")
async def run_agent(body: dict):
    """Run the agent with the given query and stream events to browser."""
    from verify_fork import MedicalTriageAgent

    agent = MedicalTriageAgent()

    async def ws_sender(data):
        await broadcast(data)

    # Create instrumented agent with WebSocket sender
    from agent_obs.emitter import EventEmitter
    from agent_obs.instrument.react import ReActInstrumentor

    emitter = EventEmitter(trace_id="medical_triage", ws_sender=ws_sender)
    instrumentor = ReActInstrumentor(agent, emitter)
    agent.run = lambda q: instrumentor.run(q)
    agent._emitter = emitter
    agent._instrumentor = instrumentor

    global_state["instrumentor"] = instrumentor

    # Run the agent
    query = body.get("query", "Patient has mild discomfort")
    result = await agent.run(query)
    return {"status": "completed", "result": result}


@app.get("/")
def root():
    """Serve demo.html at root path."""
    return FileResponse("demo.html")
