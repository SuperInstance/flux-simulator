"""
FLUX Fleet Simulator — simulate multi-agent fleet with I2I coordination.

Simulates vessels executing FLUX programs, exchanging messages via I2I,
and coordinating tasks through Tom Sawyer protocol.
"""
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable
from enum import Enum


class VesselState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING = "waiting"
    COMMS = "comms"
    HALTED = "halted"


class MessageType(Enum):
    TASK = "task"
    RESULT = "result"
    BEACON = "beacon"
    FENCE = "fence"
    CLAIM = "claim"
    COMPLETE = "complete"
    HANDSHAKE = "handshake"
    BOTTLE = "bottle"


@dataclass
class Message:
    sender: str
    recipient: str
    msg_type: MessageType
    payload: Dict
    timestamp: float = 0.0
    
    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()


@dataclass
class Task:
    task_id: str
    description: str
    bytecode: List[int]
    difficulty: int  # 1-5
    assigned_to: Optional[str] = None
    completed: bool = False
    result: Optional[Dict] = None
    fence_id: Optional[str] = None


@dataclass
class VesselConfig:
    name: str
    vessel_type: str  # lighthouse, vessel, scout, barnacle
    max_regs: int = 64
    max_stack: int = 4096
    speed: float = 1.0  # relative execution speed
    capabilities: List[str] = field(default_factory=list)


class SimulatedVessel:
    """A vessel in the fleet simulation."""
    
    def __init__(self, config: VesselConfig):
        self.config = config
        self.state = VesselState.IDLE
        self.regs = [0] * config.max_regs
        self.stack = [0] * config.max_stack
        self.sp = config.max_stack
        self.pc = 0
        self.cycles = 0
        self.mailbox: List[Message] = []
        self.completed_tasks: List[str] = []
        self.merit_badges: List[str] = []
    
    def execute(self, bytecode: List[int], initial: Dict[int, int] = None, 
                max_cycles: int = 10000) -> Dict[int, int]:
        self.regs = [0] * self.config.max_regs
        self.stack = [0] * self.config.max_stack
        self.sp = self.config.max_stack
        self.pc = 0
        self.cycles = 0
        self.state = VesselState.RUNNING
        
        if initial:
            for k, v in initial.items():
                self.regs[k] = v
        
        def sb(b): return b - 256 if b > 127 else b
        bc = bytes(bytecode)
        
        while self.pc < len(bc) and self.cycles < int(max_cycles / self.config.speed):
            op = bc[self.pc]; self.cycles += 1
            if op == 0x00: break
            elif op == 0x08: self.regs[bc[self.pc+1]] += 1; self.pc += 2
            elif op == 0x09: self.regs[bc[self.pc+1]] -= 1; self.pc += 2
            elif op == 0x0C: self.sp -= 1; self.stack[self.sp] = self.regs[bc[self.pc+1]]; self.pc += 2
            elif op == 0x0D: self.regs[bc[self.pc+1]] = self.stack[self.sp]; self.sp += 1; self.pc += 2
            elif op == 0x18: self.regs[bc[self.pc+1]] = sb(bc[self.pc+2]); self.pc += 3
            elif op == 0x20: self.regs[bc[self.pc+1]] = self.regs[bc[self.pc+2]] + self.regs[bc[self.pc+3]]; self.pc += 4
            elif op == 0x21: self.regs[bc[self.pc+1]] = self.regs[bc[self.pc+2]] - self.regs[bc[self.pc+3]]; self.pc += 4
            elif op == 0x22: self.regs[bc[self.pc+1]] = self.regs[bc[self.pc+2]] * self.regs[bc[self.pc+3]]; self.pc += 4
            elif op == 0x2C: self.regs[bc[self.pc+1]] = 1 if self.regs[bc[self.pc+2]] == self.regs[bc[self.pc+3]] else 0; self.pc += 4
            elif op == 0x3A: self.regs[bc[self.pc+1]] = self.regs[bc[self.pc+2]]; self.pc += 4
            elif op == 0x3C:
                if self.regs[bc[self.pc+1]] == 0: self.pc += sb(bc[self.pc+2])
                else: self.pc += 4
            elif op == 0x3D:
                if self.regs[bc[self.pc+1]] != 0: self.pc += sb(bc[self.pc+2])
                else: self.pc += 4
            else: self.pc += 1
        
        self.state = VesselState.IDLE
        return {i: self.regs[i] for i in range(16)}
    
    def send(self, recipient: str, msg_type: MessageType, payload: Dict) -> Message:
        msg = Message(self.config.name, recipient, msg_type, payload)
        return msg
    
    def receive(self, msg: Message):
        self.mailbox.append(msg)
    
    def process_mailbox(self) -> List[Message]:
        msgs = self.mailbox[:]
        self.mailbox.clear()
        self.state = VesselState.COMMS
        return msgs


class FleetSimulator:
    """Simulate the full fleet with task coordination."""
    
    def __init__(self):
        self.vessels: Dict[str, SimulatedVessel] = {}
        self.message_queue: List[Message] = []
        self.tasks: Dict[str, Task] = {}
        self.tick = 0
        self.event_log: List[str] = []
    
    def add_vessel(self, config: VesselConfig):
        self.vessels[config.name] = SimulatedVessel(config)
        self._log(f"Vessel {config.name} ({config.vessel_type}) joined fleet")
    
    def post_task(self, task: Task):
        self.tasks[task.task_id] = task
        self._log(f"Task posted: {task.task_id} - {task.description}")
        # Broadcast to all vessels
        for name in self.vessels:
            self.message_queue.append(Message(
                "coordinator", name, MessageType.TASK,
                {"task_id": task.task_id, "difficulty": task.difficulty}
            ))
    
    def step(self) -> bool:
        """Execute one simulation step. Returns False if nothing to do."""
        self.tick += 1
        
        # Deliver messages
        while self.message_queue:
            msg = self.message_queue.pop(0)
            if msg.recipient in self.vessels:
                self.vessels[msg.recipient].receive(msg)
        
        # Each vessel processes
        any_active = False
        for name, vessel in self.vessels.items():
            msgs = vessel.process_mailbox()
            for msg in msgs:
                if msg.msg_type == MessageType.TASK:
                    task_id = msg.payload.get("task_id")
                    task = self.tasks.get(task_id)
                    if task and not task.assigned_to and not task.completed:
                        # Tom Sawyer: volunteer for the task
                        if vessel.config.vessel_type != "lighthouse":
                            task.assigned_to = name
                            vessel.state = VesselState.RUNNING
                            result = vessel.execute(task.bytecode)
                            task.completed = True
                            task.result = result
                            vessel.completed_tasks.append(task_id)
                            self._log(f"{name} completed task {task_id}")
                            any_active = True
                elif msg.msg_type == MessageType.BEACON:
                    self._log(f"{name} received beacon from {msg.sender}")
                    any_active = True
        
        return any_active or bool(self.message_queue)
    
    def run(self, max_ticks: int = 100) -> Dict:
        """Run simulation until idle or max ticks."""
        for _ in range(max_ticks):
            if not self.step():
                break
        return self.status()
    
    def status(self) -> Dict:
        completed = sum(1 for t in self.tasks.values() if t.completed)
        return {
            "tick": self.tick,
            "vessels": len(self.vessels),
            "tasks_total": len(self.tasks),
            "tasks_completed": completed,
            "vessel_status": {
                name: {
                    "state": v.state.value,
                    "cycles": v.cycles,
                    "completed_tasks": len(v.completed_tasks),
                    "mailbox": len(v.mailbox),
                }
                for name, v in self.vessels.items()
            },
            "event_log": self.event_log[-20:],
        }
    
    def _log(self, msg: str):
        self.event_log.append(f"[t{self.tick}] {msg}")


# ── Tests ──────────────────────────────────────────────

import unittest


class TestSimulator(unittest.TestCase):
    def test_create_vessel(self):
        v = SimulatedVessel(VesselConfig("test", "vessel"))
        self.assertEqual(v.config.name, "test")
        self.assertEqual(v.state, VesselState.IDLE)
    
    def test_execute_program(self):
        v = SimulatedVessel(VesselConfig("test", "vessel"))
        result = v.execute([0x18, 0, 42, 0x00])
        self.assertEqual(result[0], 42)
    
    def test_fleet_simulation(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("oracle1", "lighthouse", speed=1.5))
        sim.add_vessel(VesselConfig("jetson1", "vessel", speed=1.0))
        
        sim.post_task(Task("t1", "compute 42", [0x18, 0, 42, 0x00], 1))
        result = sim.run()
        self.assertEqual(result["tasks_completed"], 1)
    
    def test_message_delivery(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("a", "vessel"))
        sim.message_queue.append(Message("b", "a", MessageType.BEACON, {}))
        sim.step()
        self.assertGreater(len(sim.event_log), 1)
    
    def test_tom_sawyer(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("worker1", "vessel"))
        sim.add_vessel(VesselConfig("worker2", "vessel"))
        
        sim.post_task(Task("t1", "add numbers",
            [0x18,0,10, 0x18,1,20, 0x20,2,0,1, 0x00], 1))
        result = sim.run()
        self.assertEqual(result["tasks_completed"], 1)
    
    def test_status_report(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        status = sim.status()
        self.assertIn("vessels", status)
        self.assertIn("v1", status["vessel_status"])
    
    def test_event_log(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        self.assertGreater(len(sim.event_log), 0)
    
    def test_multi_task(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("worker", "vessel", speed=2.0))
        
        for i in range(5):
            sim.post_task(Task(f"t{i}", f"task {i}", [0x18, 0, i, 0x00], 1))
        
        result = sim.run(max_ticks=50)
        self.assertEqual(result["tasks_completed"], 5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
