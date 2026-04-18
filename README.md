# flux-simulator

> Multi-agent fleet simulator with FLUX bytecode execution, I2I message passing, and Tom Sawyer task coordination.

## What This Is

`flux-simulator` is a Python module that **simulates the full FLUX fleet** — multiple vessels with different types (lighthouse, vessel, scout, barnacle), each executing FLUX bytecode, exchanging I2I messages, and coordinating tasks through the Tom Sawyer volunteer protocol.

## Role in the FLUX Ecosystem

Before deploying changes to the live fleet, test them in simulation:

- **`flux-runtime`** runs actual bytecode; simulator models the fleet dynamics
- **`flux-social`** provides the social graph; simulator exercises it with message passing
- **`flux-trust`** scores agents; simulator models trust evolution over interactions
- **`flux-dream-cycle`** schedules tasks; simulator dispatches them to vessels
- **`flux-navigate`** pathfinds; simulator integrates movement into fleet scenarios
- **`flux-evolve`** mutates behaviors; simulator tests evolved strategies

## Key Features

| Feature | Description |
|---------|-------------|
| **Multi-Vessel Simulation** | Add vessels with different types, speeds, and capabilities |
| **FLUX Bytecode Execution** | Each vessel runs real FLUX bytecode |
| **I2I Message Passing** | 8 message types: TASK, RESULT, BEACON, FENCE, CLAIM, COMPLETE, HANDSHAKE, BOTTLE |
| **Tom Sawyer Protocol** | Vessels volunteer for tasks; first volunteer wins |
| **Vessel States** | IDLE, RUNNING, WAITING, COMMS, HALTED |
| **Mailbox System** | Each vessel has an inbox with process-on-read semantics |
| **Event Logging** | Full event log for simulation replay and analysis |
| **Status Reports** | Fleet-wide status with per-vessel breakdown |

## Quick Start

```python
from flux_simulator import FleetSimulator, VesselConfig, Task, MessageType, Message

sim = FleetSimulator()

# Add vessels
sim.add_vessel(VesselConfig("oracle1", "lighthouse", speed=1.5))
sim.add_vessel(VesselConfig("superz", "vessel", speed=1.0))
sim.add_vessel(VesselConfig("quill", "vessel", speed=1.0))

# Post tasks
sim.post_task(Task("t1", "compute 42", [0x18, 0, 42, 0x00], difficulty=1))
sim.post_task(Task("t2", "add numbers",
    [0x18, 0, 10, 0x18, 1, 20, 0x20, 2, 0, 1, 0x00], difficulty=2))

# Run simulation
result = sim.run(max_ticks=100)
print(f"Completed: {result['tasks_completed']}/{result['tasks_total']}")

# Inspect vessel status
for name, status in result["vessel_status"].items():
    print(f"  {name}: {status['state']} ({status['completed_tasks']} tasks)")
```

## Running Tests

```bash
python -m pytest tests/ -v
# or
python simulator.py
```

## Related Fleet Repos

- [`flux-runtime`](https://github.com/SuperInstance/flux-runtime) — Production FLUX runtime
- [`flux-social`](https://github.com/SuperInstance/flux-social) — Social graph engine
- [`flux-trust`](https://github.com/SuperInstance/flux-trust) — Trust scoring
- [`flux-dream-cycle`](https://github.com/SuperInstance/flux-dream-cycle) — Task scheduling
- [`flux-navigate`](https://github.com/SuperInstance/flux-navigate) — Pathfinding

## License

Part of the [SuperInstance](https://github.com/SuperInstance) FLUX fleet.
