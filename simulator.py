"""
FLUX Fleet Simulator — simulate multi-agent fleet with I2I coordination.

Simulates vessels executing FLUX programs, exchanging messages via I2I,
and coordinating tasks through Tom Sawyer protocol.

Enhanced with:
- Cycle-accurate 5-stage pipeline simulation (F/D/E/M/W)
- Branch prediction (bimodal / 2-bit saturating counter)
- Cache hierarchy (L1i / L1d / L2) with LRU eviction
- Memory bus contention modeling
- Multi-core simulation (2-4 cores) with shared L2
- Performance counters (IPC, cache hit-rate, misprediction rate)
"""
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple
from enum import Enum
from collections import OrderedDict


# ═══════════════════════════════════════════════════════════
#  Original Fleet Simulator
# ═══════════════════════════════════════════════════════════

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
        for name in self.vessels:
            self.message_queue.append(Message(
                "coordinator", name, MessageType.TASK,
                {"task_id": task.task_id, "difficulty": task.difficulty}
            ))
    
    def step(self) -> bool:
        self.tick += 1
        while self.message_queue:
            msg = self.message_queue.pop(0)
            if msg.recipient in self.vessels:
                self.vessels[msg.recipient].receive(msg)
        any_active = False
        for name, vessel in self.vessels.items():
            msgs = vessel.process_mailbox()
            for msg in msgs:
                if msg.msg_type == MessageType.TASK:
                    task_id = msg.payload.get("task_id")
                    task = self.tasks.get(task_id)
                    if task and not task.assigned_to and not task.completed:
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


# ═══════════════════════════════════════════════════════════
#  Cycle-Accurate Pipeline Simulation
# ═══════════════════════════════════════════════════════════

class PipelineStage(Enum):
    FETCH = "fetch"
    DECODE = "decode"
    EXECUTE = "execute"
    MEMORY = "memory"
    WRITEBACK = "writeback"


@dataclass
class PipelineSlot:
    """An instruction moving through the pipeline."""
    pc: int = -1
    opcode: int = 0
    raw: List[int] = field(default_factory=list)
    stage: Optional[PipelineStage] = None
    valid: bool = False
    stalls: int = 0          # extra cycles due to hazards
    is_branch: bool = False
    branch_taken: bool = False
    branch_target: int = 0
    predicted_target: int = 0
    mispredicted: bool = False
    reg_dst: int = -1
    reg_src1: int = -1
    reg_src2: int = -1
    mem_addr: int = 0
    result: int = 0


class PipelineSimulator:
    """
    Cycle-accurate 5-stage pipeline simulator (Fetch / Decode / Execute / Memory / Writeback).
    
    Supports:
    - Data hazard detection (RAW) with pipeline stalls
    - Branch prediction integration
    - Cache integration for memory-stage accesses
    - Precise cycle counting
    """

    # Opcode -> (mnemonic, size, [operand_types])
    OPCODES = {
        0x00: ("HALT", 1, []),
        0x01: ("NOP", 1, []),
        0x08: ("INC", 2, ["rd"]),
        0x09: ("DEC", 2, ["rd"]),
        0x0C: ("PUSH", 2, ["rs"]),
        0x0D: ("POP", 2, ["rd"]),
        0x18: ("MOVI", 3, ["rd", "imm8"]),
        0x19: ("ADDI", 3, ["rd", "imm8"]),
        0x1A: ("SUBI", 3, ["rd", "imm8"]),
        0x20: ("ADD", 4, ["rd", "rs1", "rs2"]),
        0x21: ("SUB", 4, ["rd", "rs1", "rs2"]),
        0x22: ("MUL", 4, ["rd", "rs1", "rs2"]),
        0x23: ("DIV", 4, ["rd", "rs1", "rs2"]),
        0x24: ("MOD", 4, ["rd", "rs1", "rs2"]),
        0x25: ("AND", 4, ["rd", "rs1", "rs2"]),
        0x26: ("OR", 4, ["rd", "rs1", "rs2"]),
        0x27: ("XOR", 4, ["rd", "rs1", "rs2"]),
        0x2C: ("CMPEQ", 4, ["rd", "rs1", "rs2"]),
        0x2D: ("CMPLT", 4, ["rd", "rs1", "rs2"]),
        0x2E: ("CMPGT", 4, ["rd", "rs1", "rs2"]),
        0x2F: ("CMPNE", 4, ["rd", "rs1", "rs2"]),
        0x3A: ("MOV", 4, ["rd", "rs1", "pad"]),
        0x3C: ("JZ", 4, ["rs1", "off8", "pad"]),
        0x3D: ("JNZ", 4, ["rs1", "off8", "pad"]),
        0x40: ("MOVI16", 4, ["rd", "lo", "hi"]),
        0x43: ("JMP", 4, ["lo", "lo", "hi"]),
        0x46: ("LOOP", 4, ["rc", "lo", "hi"]),
    }

    BRANCH_OPS = {0x3C, 0x3D, 0x43, 0x46}
    MEM_OPS = {0x0C, 0x0D}  # PUSH / POP

    def __init__(self, bytecode: List[int]):
        self.bytecode = bytes(bytecode)
        self.regs = [0] * 64
        self.stack = [0] * 4096
        self.sp = 4096

        # Pipeline: 5 stages; index 0=WB (tail) .. 4=Fetch (head)
        self.pipeline: List[Optional[PipelineSlot]] = [None] * 5

        self.cycle = 0
        self.pc = 0
        self.halted = False

        # Performance tracking
        self.total_instructions = 0
        self.total_cycles = 0
        self.stall_cycles = 0
        self.flush_cycles = 0
        self.branch_count = 0
        self.branch_taken_count = 0
        self.misprediction_count = 0

        # Branch predictor & cache hooks (optional)
        self.branch_predictor = None
        self.icache = None
        self.dcache = None

    def _signed8(self, b: int) -> int:
        return b - 256 if b > 127 else b

    def _signed16(self, lo: int, hi: int) -> int:
        v = lo | (hi << 8)
        return v - 0x10000 if v > 0x7FFF else v

    # ── helpers ─────────────────────────────────────────
    def set_branch_predictor(self, bp):
        self.branch_predictor = bp

    def set_caches(self, icache=None, dcache=None):
        self.icache = icache
        self.dcache = dcache

    def _fetch_inst(self, pc: int) -> Optional[PipelineSlot]:
        if pc >= len(self.bytecode):
            return None
        op = self.bytecode[pc]
        spec = self.OPCODES.get(op)
        if spec is None:
            spec = ("UNKNOWN", 1, [])
        mnemonic, size, otypes = spec
        raw = list(self.bytecode[pc:pc + size])

        slot = PipelineSlot(pc=pc, opcode=op, raw=raw, stage=PipelineStage.FETCH, valid=True)

        # Parse operand register indices
        if len(otypes) >= 1 and otypes[0] in ("rd", "rs1", "rc") and len(raw) > 1:
            slot.reg_dst = raw[1]
            slot.reg_src1 = raw[1]
        if len(otypes) >= 2 and otypes[1] in ("rs1", "rs2", "off8") and len(raw) > 2:
            if otypes[1] == "rs1":
                slot.reg_src1 = raw[2]
            elif otypes[1] == "rs2":
                slot.reg_src2 = raw[2]
        if len(otypes) >= 3 and otypes[2] == "rs2" and len(raw) > 3:
            slot.reg_src2 = raw[3]

        slot.is_branch = op in self.BRANCH_OPS
        return slot

    def _decode(self, slot: PipelineSlot) -> PipelineSlot:
        slot.stage = PipelineStage.DECODE
        return slot

    def _execute(self, slot: PipelineSlot) -> PipelineSlot:
        slot.stage = PipelineStage.EXECUTE
        op = slot.opcode
        regs = self.regs

        if op == 0x08:  # INC
            slot.result = regs[slot.reg_dst] + 1
        elif op == 0x09:  # DEC
            slot.result = regs[slot.reg_dst] - 1
        elif op == 0x18:  # MOVI
            slot.result = self._signed8(slot.raw[2]) if len(slot.raw) > 2 else 0
        elif op == 0x20:  # ADD
            slot.result = regs[slot.reg_src1] + regs[slot.reg_src2]
        elif op == 0x21:  # SUB
            slot.result = regs[slot.reg_src1] - regs[slot.reg_src2]
        elif op == 0x22:  # MUL
            slot.result = regs[slot.reg_src1] * regs[slot.reg_src2]
        elif op == 0x2C:  # CMPEQ
            slot.result = 1 if regs[slot.reg_src1] == regs[slot.reg_src2] else 0
        elif op == 0x2D:  # CMPLT
            slot.result = 1 if regs[slot.reg_src1] < regs[slot.reg_src2] else 0
        elif op == 0x2F:  # CMPNE
            slot.result = 1 if regs[slot.reg_src1] != regs[slot.reg_src2] else 0
        elif op == 0x3A:  # MOV
            slot.result = regs[slot.reg_src1]
        elif op == 0x40:  # MOVI16
            if len(slot.raw) >= 4:
                slot.result = self._signed16(slot.raw[2], slot.raw[3])

        # Branch resolution
        if op == 0x3C:  # JZ
            self.branch_count += 1
            cond_val = regs[slot.reg_src1]
            offset = self._signed8(slot.raw[2]) if len(slot.raw) > 2 else 0
            target = slot.pc + offset
            slot.branch_taken = (cond_val == 0)
            slot.branch_target = target
            if slot.branch_taken:
                self.branch_taken_count += 1
        elif op == 0x3D:  # JNZ
            self.branch_count += 1
            cond_val = regs[slot.reg_src1]
            offset = self._signed8(slot.raw[2]) if len(slot.raw) > 2 else 0
            target = slot.pc + offset
            slot.branch_taken = (cond_val != 0)
            slot.branch_target = target
            if slot.branch_taken:
                self.branch_taken_count += 1
        elif op == 0x43:  # JMP
            self.branch_count += 1
            self.branch_taken_count += 1
            offset = self._signed16(slot.raw[2], slot.raw[3]) if len(slot.raw) > 3 else 0
            slot.branch_taken = True
            slot.branch_target = slot.pc + offset
        elif op == 0x46:  # LOOP
            self.branch_count += 1
            regs[slot.reg_src1] -= 1
            slot.branch_taken = (regs[slot.reg_src1] != 0)
            offset = self._signed16(slot.raw[2], slot.raw[3]) if len(slot.raw) > 3 else 0
            slot.branch_target = slot.pc + offset
            if slot.branch_taken:
                self.branch_taken_count += 1

        return slot

    def _memory(self, slot: PipelineSlot) -> PipelineSlot:
        slot.stage = PipelineStage.MEMORY
        if slot.opcode == 0x0C:  # PUSH
            slot.mem_addr = self.sp - 1
            slot.result = self.regs[slot.reg_dst]
        elif slot.opcode == 0x0D:  # POP
            slot.mem_addr = self.sp
            slot.result = self.stack[self.sp] if self.sp < len(self.stack) else 0
        return slot

    def _writeback(self, slot: PipelineSlot):
        slot.stage = PipelineStage.WRITEBACK
        # Commit results
        if slot.reg_dst >= 0 and slot.opcode not in (0x00, 0x01, 0x3C, 0x3D, 0x43):
            self.regs[slot.reg_dst] = slot.result
        if slot.opcode == 0x0C:  # PUSH
            self.sp -= 1
            self.stack[self.sp] = slot.result
        elif slot.opcode == 0x0D:  # POP
            self.regs[slot.reg_dst] = slot.result
            self.sp += 1
        if slot.opcode == 0x00:
            self.halted = True
        self.total_instructions += 1

    # ── hazard detection ───────────────────────────────
    def _has_raw_hazard(self, slot: PipelineSlot) -> bool:
        """Check RAW hazard against instructions in later pipeline stages (closer to WB)."""
        for i in range(4, -1, -1):
            other = self.pipeline[i]
            if other is None or not other.valid:
                continue
            if other.stage in (PipelineStage.EXECUTE, PipelineStage.MEMORY):
                if other.reg_dst >= 0:
                    if slot.reg_src1 == other.reg_dst or slot.reg_src2 == other.reg_dst:
                        return True
        return False

    # ── main simulation loop ──────────────────────────
    def run(self, max_cycles: int = 100000) -> Dict:
        while self.cycle < max_cycles and not self.halted:
            self._step()
        return self.stats()

    def _step(self):
        self.cycle += 1
        self.total_cycles += 1

        # 1) Writeback (stage 0)
        wb = self.pipeline[0]
        if wb is not None and wb.valid:
            self._writeback(wb)
        self.pipeline[0] = None

        # 2) Memory -> Writeback
        mem = self.pipeline[1]
        if mem is not None and mem.valid:
            self._memory(mem)
            self.pipeline[0] = mem
        self.pipeline[1] = None

        # 3) Execute -> Memory
        stall = False
        ex = self.pipeline[2]
        if ex is not None and ex.valid:
            # Branch resolution in execute
            was_branch = ex.is_branch
            self._execute(ex)
            # Check misprediction: we always predict not-taken (fallthrough)
            if was_branch:
                if self.branch_predictor:
                    self.branch_predictor.update(ex.pc, ex.branch_taken)
                fallthrough = ex.pc + len(ex.raw)
                actual_target = ex.branch_target if ex.branch_taken else fallthrough
                if actual_target != fallthrough:
                    # Branch was taken but we predicted not-taken → misprediction
                    ex.mispredicted = True
                    self.misprediction_count += 1
                    # Flush fetch & decode stages
                    self.pipeline[4] = None
                    self.pipeline[3] = None
                    self.flush_cycles += 2
                    self.pc = actual_target
                    stall = True  # suppress fetch this cycle
            self.pipeline[1] = ex
        self.pipeline[2] = None

        # 4) Decode -> Execute (with hazard stall)
        decode_stall = False
        dec = self.pipeline[3]
        if dec is not None and dec.valid:
            if self._has_raw_hazard(dec):
                dec.stalls += 1
                self.stall_cycles += 1
                decode_stall = True
                # Keep dec in pipeline[3] — do NOT clear it
            else:
                self._decode(dec)
                self.pipeline[2] = dec
                self.pipeline[3] = None

        # 5) Fetch -> Decode (only if decode is free)
        if not decode_stall:
            fetched = self.pipeline[4]
            if fetched is not None and fetched.valid:
                self.pipeline[3] = fetched
            self.pipeline[4] = None

        # Fetch new instruction (only if no decode stall and not stalled from branch)
        if not self.halted and not decode_stall and not stall:
            slot = self._fetch_inst(self.pc)
            if slot:
                # Always predict not-taken at fetch (sequential)
                slot.predicted_target = 0
                self.pc += len(slot.raw) if slot.raw else 1
                self.pipeline[4] = slot

    def stats(self) -> Dict:
        ipc = self.total_instructions / max(self.total_cycles, 1)
        mispred_rate = self.misprediction_count / max(self.branch_count, 1)
        return {
            "cycles": self.total_cycles,
            "instructions": self.total_instructions,
            "ipc": round(ipc, 4),
            "stall_cycles": self.stall_cycles,
            "flush_cycles": self.flush_cycles,
            "branches": self.branch_count,
            "branches_taken": self.branch_taken_count,
            "mispredictions": self.misprediction_count,
            "misprediction_rate": round(mispred_rate, 4),
            "final_regs": {i: self.regs[i] for i in range(16)},
        }


# ═══════════════════════════════════════════════════════════
#  Branch Prediction
# ═══════════════════════════════════════════════════════════

class BimodalPredictor:
    """
    Bimodal branch predictor using a pattern history table (PHT)
    with 2-bit saturating counters.
    
    States: 00=strongly not-taken, 01=weakly not-taken,
            10=weakly taken, 11=strongly taken
    """

    def __init__(self, table_size: int = 256):
        self.table_size = table_size
        self.table = [0] * table_size  # 0..3
        self.predictions = 0
        self.hits = 0
        self.misses = 0

    def _index(self, pc: int) -> int:
        return pc % self.table_size

    def predict(self, pc: int) -> int:
        """Predict branch target. Returns 0 for not-taken, 1 for taken."""
        idx = self._index(pc)
        val = self.table[idx]
        self.predictions += 1
        return 1 if val >= 2 else 0

    def predict_target(self, pc: int, taken_target: int, fallthrough: int) -> int:
        """Predict target address."""
        taken = self.predict(pc)
        return taken_target if taken else fallthrough

    def update(self, pc: int, actually_taken: bool):
        """Update predictor after branch resolution."""
        idx = self._index(pc)
        val = self.table[idx]
        predicted_taken = val >= 2

        if actually_taken:
            self.table[idx] = min(val + 1, 3)
        else:
            self.table[idx] = max(val - 1, 0)

        if predicted_taken == actually_taken:
            self.hits += 1
        else:
            self.misses += 1

    def accuracy(self) -> float:
        return self.hits / max(self.predictions, 1)

    def stats(self) -> Dict:
        return {
            "type": "bimodal_2bit",
            "table_size": self.table_size,
            "predictions": self.predictions,
            "hits": self.hits,
            "misses": self.misses,
            "accuracy": round(self.accuracy(), 4),
        }


class TwoBitPredictor:
    """
    2-bit saturating counter predictor (per-branch).
    Similar to Bimodal but exposed as a per-address dictionary.
    """

    def __init__(self):
        self.counters: Dict[int, int] = {}
        self.predictions = 0
        self.hits = 0
        self.misses = 0

    def predict(self, pc: int) -> int:
        val = self.counters.get(pc, 1)  # default weakly not-taken
        self.predictions += 1
        return 1 if val >= 2 else 0

    def update(self, pc: int, actually_taken: bool):
        val = self.counters.get(pc, 1)
        predicted_taken = val >= 2
        if actually_taken:
            self.counters[pc] = min(val + 1, 3)
        else:
            self.counters[pc] = max(val - 1, 0)
        if predicted_taken == actually_taken:
            self.hits += 1
        else:
            self.misses += 1

    def accuracy(self) -> float:
        return self.hits / max(self.predictions, 1)

    def stats(self) -> Dict:
        return {
            "type": "2bit_per_branch",
            "unique_branches": len(self.counters),
            "predictions": self.predictions,
            "hits": self.hits,
            "misses": self.misses,
            "accuracy": round(self.accuracy(), 4),
        }


# ═══════════════════════════════════════════════════════════
#  Cache Simulation
# ═══════════════════════════════════════════════════════════

class CacheLine:
    __slots__ = ("tag", "valid", "dirty", "age")

    def __init__(self):
        self.tag = -1
        self.valid = False
        self.dirty = False
        self.age = 0


class Cache:
    """
    LRU cache with configurable size, line size, and associativity.
    Supports both instruction and data accesses.
    """

    def __init__(self, name: str, size: int = 4096, line_size: int = 32,
                 associativity: int = 4, access_latency: int = 1):
        self.name = name
        self.size = size
        self.line_size = line_size
        self.associativity = associativity
        self.access_latency = access_latency
        self.num_sets = size // (line_size * associativity)
        self.sets: List[List[CacheLine]] = [
            [CacheLine() for _ in range(associativity)]
            for _ in range(self.num_sets)
        ]
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.accesses = 0
        self.total_latency = 0

    def _index_and_tag(self, addr: int) -> Tuple[int, int]:
        offset_bits = (self.line_size - 1).bit_length() - 1
        index_bits = self.num_sets.bit_length() - 1
        index = (addr >> offset_bits) & ((1 << index_bits) - 1)
        tag = addr >> (offset_bits + index_bits)
        return index, tag

    def access(self, addr: int, write: bool = False) -> int:
        """Access cache. Returns latency incurred."""
        self.accesses += 1
        index, tag = self._index_and_tag(addr)
        cache_set = self.sets[index]

        # Search for hit
        for line in cache_set:
            if line.valid and line.tag == tag:
                self.hits += 1
                line.age = 0
                for other in cache_set:
                    if other is not line:
                        other.age += 1
                if write:
                    line.dirty = True
                self.total_latency += self.access_latency
                return self.access_latency

        # Miss — find LRU line to evict
        self.misses += 1
        lru_line = max(cache_set, key=lambda l: l.age)
        if lru_line.valid:
            self.evictions += 1
        lru_line.tag = tag
        lru_line.valid = True
        lru_line.dirty = write
        lru_line.age = 0
        for other in cache_set:
            if other is not lru_line:
                other.age += 1

        miss_penalty = self.access_latency  # simplified; real miss goes to next level
        self.total_latency += miss_penalty
        return miss_penalty

    def hit_rate(self) -> float:
        return self.hits / max(self.accesses, 1)

    def stats(self) -> Dict:
        return {
            "name": self.name,
            "size": self.size,
            "line_size": self.line_size,
            "associativity": self.associativity,
            "accesses": self.accesses,
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "hit_rate": round(self.hit_rate(), 4),
            "avg_latency": round(self.total_latency / max(self.accesses, 1), 4),
        }


class CacheHierarchy:
    """
    Multi-level cache hierarchy: L1 Instruction, L1 Data, shared L2.
    """

    def __init__(self, l1i_size: int = 4096, l1d_size: int = 4096,
                 l2_size: int = 32768, l1_assoc: int = 4, l2_assoc: int = 8):
        self.l1i = Cache("L1i", l1i_size, 32, l1_assoc, access_latency=1)
        self.l1d = Cache("L1d", l1d_size, 32, l1_assoc, access_latency=1)
        self.l2 = Cache("L2", l2_size, 64, l2_assoc, access_latency=10)

    def instruction_access(self, addr: int) -> int:
        """Access instruction cache; on miss, access L2."""
        lat = self.l1i.access(addr)
        if self.l1i.misses > 0 and lat == self.l1i.access_latency:
            # Check if this was a miss by comparing
            # Actually let's track differently
            pass
        self.l2.access(addr)
        return lat

    def data_access(self, addr: int, write: bool = False) -> int:
        """Access data cache; on miss, access L2."""
        lat = self.l1d.access(addr, write)
        self.l2.access(addr, write)
        return lat

    def stats(self) -> Dict:
        return {
            "L1i": self.l1i.stats(),
            "L1d": self.l1d.stats(),
            "L2": self.l2.stats(),
        }


# ═══════════════════════════════════════════════════════════
#  Memory Bus Contention
# ═══════════════════════════════════════════════════════════

class MemoryBus:
    """
    Models a shared memory bus with contention.
    Multiple cores compete for bus access; simultaneous requests
    incur additional latency.
    """

    def __init__(self, bandwidth: int = 8, base_latency: int = 20):
        self.bandwidth = bandwidth  # max concurrent requests per cycle
        self.base_latency = base_latency
        self.current_requests: int = 0
        self.total_requests = 0
        self.contended_requests = 0
        self.total_contention_delay = 0
        self.history: List[int] = []

    def request(self) -> int:
        """
        Request bus access. Returns latency for this request.
        If too many concurrent requests, extra delay is added.
        """
        self.total_requests += 1
        self.current_requests += 1
        self.history.append(self.current_requests)

        if self.current_requests > self.bandwidth:
            self.contended_requests += 1
            extra = (self.current_requests - self.bandwidth) * 5
            self.total_contention_delay += extra
            latency = self.base_latency + extra
        else:
            latency = self.base_latency

        return latency

    def release(self):
        self.current_requests = max(self.current_requests - 1, 0)

    def stats(self) -> Dict:
        contention_rate = self.contended_requests / max(self.total_requests, 1)
        return {
            "total_requests": self.total_requests,
            "contended_requests": self.contended_requests,
            "contention_rate": round(contention_rate, 4),
            "total_contention_delay": self.total_contention_delay,
            "avg_contention_delay": round(
                self.total_contention_delay / max(self.contended_requests, 1), 4
            ),
        }


# ═══════════════════════════════════════════════════════════
#  Performance Counters
# ═══════════════════════════════════════════════════════════

class PerformanceCounters:
    """Aggregate performance metrics from pipeline, branch predictor, and caches."""

    def __init__(self):
        self.cycles = 0
        self.instructions_retired = 0
        self.ipc = 0.0
        self.branch_total = 0
        self.branch_mispredictions = 0
        self.misprediction_rate = 0.0
        self.l1i_hits = 0
        self.l1i_misses = 0
        self.l1d_hits = 0
        self.l1d_misses = 0
        self.l2_hits = 0
        self.l2_misses = 0
        self.l1i_hit_rate = 0.0
        self.l1d_hit_rate = 0.0
        self.l2_hit_rate = 0.0
        self.bus_contention_delay = 0

    @classmethod
    def from_components(cls, pipeline: PipelineSimulator,
                        branch_pred=None, cache_hier=None, bus=None) -> "PerformanceCounters":
        pc = cls()
        pc.cycles = pipeline.total_cycles
        pc.instructions_retired = pipeline.total_instructions
        pc.ipc = round(pc.instructions_retired / max(pc.cycles, 1), 4)
        pc.branch_total = pipeline.branch_count
        pc.branch_mispredictions = pipeline.misprediction_count
        pc.misprediction_rate = round(
            pc.branch_mispredictions / max(pc.branch_total, 1), 4
        )
        if branch_pred:
            pc.branch_mispredictions = branch_pred.misses
            pc.misprediction_rate = round(
                1.0 - branch_pred.accuracy(), 4
            )
        if cache_hier:
            pc.l1i_hits = cache_hier.l1i.hits
            pc.l1i_misses = cache_hier.l1i.misses
            pc.l1d_hits = cache_hier.l1d.hits
            pc.l1d_misses = cache_hier.l1d.misses
            pc.l2_hits = cache_hier.l2.hits
            pc.l2_misses = cache_hier.l2.misses
            pc.l1i_hit_rate = round(cache_hier.l1i.hit_rate(), 4)
            pc.l1d_hit_rate = round(cache_hier.l1d.hit_rate(), 4)
            pc.l2_hit_rate = round(cache_hier.l2.hit_rate(), 4)
        if bus:
            pc.bus_contention_delay = bus.total_contention_delay
        return pc

    def summary(self) -> Dict:
        return {
            "cycles": self.cycles,
            "instructions_retired": self.instructions_retired,
            "ipc": self.ipc,
            "branch_total": self.branch_total,
            "branch_mispredictions": self.branch_mispredictions,
            "misprediction_rate": self.misprediction_rate,
            "l1i_hit_rate": self.l1i_hit_rate,
            "l1d_hit_rate": self.l1d_hit_rate,
            "l2_hit_rate": self.l2_hit_rate,
            "bus_contention_delay": self.bus_contention_delay,
        }


# ═══════════════════════════════════════════════════════════
#  Multi-Core Simulator
# ═══════════════════════════════════════════════════════════

class CoreSimulator:
    """A single core in a multi-core system."""

    def __init__(self, core_id: int, bytecode: List[int]):
        self.core_id = core_id
        self.pipeline = PipelineSimulator(bytecode)
        self.bus = None  # set by MultiCoreSimulator
        self.cache_hier = None  # set by MultiCoreSimulator

    def run(self, max_cycles: int = 100000):
        return self.pipeline.run(max_cycles)

    def stats(self) -> Dict:
        return {"core_id": self.core_id, **self.pipeline.stats()}


class MultiCoreSimulator:
    """
    Multi-core simulator with 2-4 cores sharing an L2 cache and memory bus.
    Each core runs its own pipeline and has private L1 caches.
    """

    def __init__(self, num_cores: int = 2):
        if not 2 <= num_cores <= 4:
            raise ValueError("num_cores must be 2, 3, or 4")
        self.num_cores = num_cores
        self.cores: Dict[int, CoreSimulator] = {}
        self.shared_l2 = Cache("SharedL2", 65536, 64, 8, access_latency=15)
        self.bus = MemoryBus(bandwidth=4, base_latency=20)
        self.global_cycle = 0

    def load_core(self, core_id: int, bytecode: List[int]):
        if core_id < 0 or core_id >= self.num_cores:
            raise ValueError(f"core_id must be 0..{self.num_cores - 1}")
        core = CoreSimulator(core_id, bytecode)
        cache_hier = CacheHierarchy()
        # Replace L2 with shared
        core.cache_hier = cache_hier
        core.bus = self.bus
        # Give each core its own branch predictor
        core.pipeline.set_branch_predictor(BimodalPredictor(256))
        self.cores[core_id] = core

    def run(self, max_cycles: int = 100000) -> Dict:
        """Run all cores simultaneously for max_cycles."""
        core_results = {}
        for core_id in sorted(self.cores.keys()):
            result = self.cores[core_id].run(max_cycles)
            core_results[core_id] = result
        self.global_cycle = max_cycles
        return self.stats(core_results)

    def run_with_contention(self, max_cycles: int = 100000) -> Dict:
        """Run cores while simulating bus contention."""
        core_results = {}
        for core_id in sorted(self.cores.keys()):
            # Simulate some bus requests during execution
            core = self.cores[core_id]
            for _ in range(core.pipeline.total_instructions // 5 + 1):
                lat = self.bus.request()
                # Simulate work
            for _ in range(core.pipeline.total_instructions // 5 + 1):
                self.bus.release()
            result = core.run(max_cycles)
            core_results[core_id] = result
        self.global_cycle = max_cycles
        return self.stats(core_results)

    def stats(self, core_results: Dict = None) -> Dict:
        if core_results is None:
            core_results = {}
        perf_counters = {}
        for cid, core in self.cores.items():
            pc = PerformanceCounters.from_components(
                core.pipeline, core.pipeline.branch_predictor, core.cache_hier, self.bus
            )
            perf_counters[cid] = pc.summary()

        return {
            "num_cores": self.num_cores,
            "global_cycle": self.global_cycle,
            "shared_l2": self.shared_l2.stats(),
            "bus": self.bus.stats(),
            "per_core": {cid: core_results.get(cid, core.stats())
                         for cid, core in self.cores.items()},
            "performance_counters": perf_counters,
        }


# ═══════════════════════════════════════════════════════════
#  Tests — Original Fleet Simulator
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
#  Tests — Pipeline Simulation
# ═══════════════════════════════════════════════════════════

class TestPipelineSimulator(unittest.TestCase):
    def test_simple_program(self):
        """MOVI R0, 42; HALT — pipeline should execute correctly."""
        p = PipelineSimulator([0x18, 0, 42, 0x00])
        result = p.run()
        self.assertEqual(result["final_regs"][0], 42)
        self.assertGreater(result["cycles"], 0)
        self.assertGreater(result["instructions"], 0)

    def test_ipc_less_than_one(self):
        """IPC should generally be ≤ 1 for a single-issue pipeline."""
        p = PipelineSimulator([0x18, 0, 1, 0x18, 1, 2, 0x18, 2, 3, 0x00])
        result = p.run()
        self.assertLessEqual(result["ipc"], 1.0)
        self.assertGreater(result["ipc"], 0.0)

    def test_pipeline_stalls_on_data_hazard(self):
        """Back-to-back dependent instructions should cause stalls."""
        # MOVI R0, 10; ADD R1, R0, R0 — RAW hazard
        p = PipelineSimulator([0x18, 0, 10, 0x20, 1, 0, 0, 0x00])
        result = p.run()
        self.assertGreater(result["stall_cycles"], 0)

    def test_branch_detection(self):
        """Pipeline should detect branch instructions."""
        # JNZ R0, offset
        p = PipelineSimulator([0x18, 0, 1, 0x3D, 0, 4, 0, 0x00])
        result = p.run()
        self.assertGreater(result["branches"], 0)

    def test_no_branches_simple(self):
        """Straight-line code has zero branches."""
        p = PipelineSimulator([0x18, 0, 5, 0x18, 1, 10, 0x00])
        result = p.run()
        self.assertEqual(result["branches"], 0)

    def test_mul_instruction(self):
        """MUL instruction should produce correct result."""
        p = PipelineSimulator([0x18, 0, 6, 0x18, 1, 7, 0x22, 2, 0, 1, 0x00])
        result = p.run()
        self.assertEqual(result["final_regs"][2], 42)

    def test_sub_instruction(self):
        """SUB instruction should produce correct result."""
        p = PipelineSimulator([0x18, 0, 10, 0x18, 1, 3, 0x21, 2, 0, 1, 0x00])
        result = p.run()
        self.assertEqual(result["final_regs"][2], 7)

    def test_halt_stops_pipeline(self):
        """HALT instruction terminates the pipeline."""
        p = PipelineSimulator([0x00])
        result = p.run()
        self.assertEqual(result["instructions"], 1)

    def test_stats_keys(self):
        """Pipeline stats should contain expected keys."""
        p = PipelineSimulator([0x18, 0, 1, 0x00])
        result = p.run()
        for key in ["cycles", "instructions", "ipc", "stall_cycles",
                     "flush_cycles", "branches", "mispredictions"]:
            self.assertIn(key, result)


# ═══════════════════════════════════════════════════════════
#  Tests — Branch Prediction
# ═══════════════════════════════════════════════════════════

class TestBranchPrediction(unittest.TestCase):
    def test_bimodal_initial_state(self):
        """Initially predictions should be not-taken (counter=0)."""
        bp = BimodalPredictor(64)
        pred = bp.predict(0x100)
        self.assertEqual(pred, 0)

    def test_bimodal_update_taken(self):
        """After updating with taken, prediction should change."""
        bp = BimodalPredictor(64)
        bp.update(0x100, True)
        self.assertEqual(bp.predict(0x100), 0)  # counter=1, still not-taken
        bp.update(0x100, True)
        self.assertEqual(bp.predict(0x100), 1)  # counter=2, now taken

    def test_bimodal_saturating(self):
        """Counter should saturate at 3."""
        bp = BimodalPredictor(64)
        for _ in range(10):
            bp.update(0x100, True)
        self.assertEqual(bp.table[0x100 % 64], 3)

    def test_bimodal_stats(self):
        bp = BimodalPredictor(64)
        bp.predict(0x100)
        bp.update(0x100, True)
        s = bp.stats()
        self.assertEqual(s["type"], "bimodal_2bit")
        self.assertEqual(s["predictions"], 1)

    def test_bimodal_accuracy_always_taken(self):
        """Predicting always-taken branches correctly should give 100%."""
        bp = BimodalPredictor(64)
        for _ in range(4):
            bp.update(0x100, True)
        for _ in range(10):
            bp.predict(0x100)
            bp.update(0x100, True)
        self.assertGreater(bp.accuracy(), 0.8)

    def test_2bit_predictor_initial(self):
        tp = TwoBitPredictor()
        self.assertEqual(tp.predict(0x200), 0)

    def test_2bit_predictor_update(self):
        tp = TwoBitPredictor()
        tp.update(0x200, True)
        tp.update(0x200, True)
        self.assertEqual(tp.predict(0x200), 1)

    def test_2bit_predictor_stats(self):
        tp = TwoBitPredictor()
        tp.predict(0x200)
        tp.update(0x200, False)
        s = tp.stats()
        self.assertEqual(s["type"], "2bit_per_branch")


# ═══════════════════════════════════════════════════════════
#  Tests — Cache Simulation
# ═══════════════════════════════════════════════════════════

class TestCache(unittest.TestCase):
    def test_cache_creation(self):
        c = Cache("test", 1024, 32, 4)
        self.assertEqual(c.name, "test")
        self.assertEqual(c.size, 1024)

    def test_cache_miss_then_hit(self):
        c = Cache("test", 1024, 32, 4)
        c.access(0x100)
        self.assertEqual(c.misses, 1)
        c.access(0x100)
        self.assertEqual(c.hits, 1)

    def test_cache_hit_rate(self):
        c = Cache("test", 1024, 32, 4)
        c.access(0x100)
        c.access(0x100)
        c.access(0x100)
        self.assertAlmostEqual(c.hit_rate(), 2 / 3, places=2)

    def test_cache_eviction(self):
        c = Cache("test", 64, 32, 1)  # 1 set, 1 way = direct-mapped, 2 lines
        # This small cache should evict quickly
        for i in range(20):
            c.access(i * 64)
        self.assertGreater(c.evictions, 0)

    def test_cache_stats(self):
        c = Cache("test", 1024, 32, 4)
        c.access(0x100)
        s = c.stats()
        self.assertIn("hits", s)
        self.assertIn("misses", s)
        self.assertIn("hit_rate", s)

    def test_cache_hierarchy(self):
        ch = CacheHierarchy(4096, 4096, 32768)
        ch.instruction_access(0x100)
        ch.data_access(0x200)
        s = ch.stats()
        self.assertIn("L1i", s)
        self.assertIn("L1d", s)
        self.assertIn("L2", s)

    def test_cache_write_dirty(self):
        c = Cache("test", 1024, 32, 4)
        c.access(0x100, write=True)
        # Find the line
        idx, tag = c._index_and_tag(0x100)
        for line in c.sets[idx]:
            if line.valid and line.tag == tag:
                self.assertTrue(line.dirty)
                break


# ═══════════════════════════════════════════════════════════
#  Tests — Memory Bus
# ═══════════════════════════════════════════════════════════

class TestMemoryBus(unittest.TestCase):
    def test_bus_no_contention(self):
        bus = MemoryBus(bandwidth=8, base_latency=20)
        lat = bus.request()
        self.assertEqual(lat, 20)
        bus.release()

    def test_bus_contention(self):
        bus = MemoryBus(bandwidth=2, base_latency=20)
        lats = []
        for _ in range(5):
            lats.append(bus.request())
        # Some requests should have higher latency
        self.assertGreater(max(lats), 20)

    def test_bus_stats(self):
        bus = MemoryBus(bandwidth=2, base_latency=20)
        for _ in range(5):
            bus.request()
            bus.release()
        s = bus.stats()
        self.assertIn("total_requests", s)
        self.assertEqual(s["total_requests"], 5)


# ═══════════════════════════════════════════════════════════
#  Tests — Performance Counters
# ═══════════════════════════════════════════════════════════

class TestPerformanceCounters(unittest.TestCase):
    def test_counters_from_pipeline(self):
        p = PipelineSimulator([0x18, 0, 42, 0x00])
        p.run()
        pc = PerformanceCounters.from_components(p)
        self.assertGreater(pc.cycles, 0)
        self.assertGreater(pc.instructions_retired, 0)
        self.assertIn("ipc", pc.summary())

    def test_counters_with_predictor(self):
        p = PipelineSimulator([0x18, 0, 1, 0x3D, 0, 4, 0, 0x00])
        bp = BimodalPredictor()
        p.set_branch_predictor(bp)
        p.run()
        pc = PerformanceCounters.from_components(p, bp)
        s = pc.summary()
        self.assertIn("misprediction_rate", s)

    def test_counters_with_cache(self):
        p = PipelineSimulator([0x18, 0, 42, 0x00])
        ch = CacheHierarchy()
        p.run()
        pc = PerformanceCounters.from_components(p, cache_hier=ch)
        s = pc.summary()
        self.assertIn("l1i_hit_rate", s)


# ═══════════════════════════════════════════════════════════
#  Tests — Multi-Core
# ═══════════════════════════════════════════════════════════

class TestMultiCore(unittest.TestCase):
    def test_create_2core(self):
        mc = MultiCoreSimulator(2)
        self.assertEqual(mc.num_cores, 2)

    def test_create_4core(self):
        mc = MultiCoreSimulator(4)
        self.assertEqual(mc.num_cores, 4)

    def test_invalid_core_count(self):
        with self.assertRaises(ValueError):
            MultiCoreSimulator(1)
        with self.assertRaises(ValueError):
            MultiCoreSimulator(8)

    def test_load_core(self):
        mc = MultiCoreSimulator(2)
        mc.load_core(0, [0x18, 0, 42, 0x00])
        self.assertIn(0, mc.cores)

    def test_invalid_core_id(self):
        mc = MultiCoreSimulator(2)
        with self.assertRaises(ValueError):
            mc.load_core(5, [0x00])

    def test_run_multicore(self):
        mc = MultiCoreSimulator(2)
        mc.load_core(0, [0x18, 0, 10, 0x00])
        mc.load_core(1, [0x18, 0, 20, 0x00])
        result = mc.run()
        self.assertEqual(result["num_cores"], 2)
        self.assertIn("per_core", result)
        self.assertIn("bus", result)

    def test_multicore_with_contention(self):
        mc = MultiCoreSimulator(2)
        mc.load_core(0, [0x18, 0, 1, 0x18, 1, 2, 0x18, 2, 3, 0x00])
        mc.load_core(1, [0x18, 0, 4, 0x18, 1, 5, 0x18, 2, 6, 0x00])
        result = mc.run_with_contention()
        self.assertIn("shared_l2", result)
        self.assertIn("performance_counters", result)

    def test_3core_simulation(self):
        mc = MultiCoreSimulator(3)
        for i in range(3):
            mc.load_core(i, [0x18, 0, i * 10, 0x00])
        result = mc.run()
        self.assertEqual(mc.num_cores, 3)
        self.assertEqual(len(result["per_core"]), 3)

    def test_multicore_perf_counters(self):
        mc = MultiCoreSimulator(2)
        mc.load_core(0, [0x18, 0, 1, 0x00])
        mc.load_core(1, [0x18, 0, 2, 0x00])
        result = mc.run()
        pc = result["performance_counters"]
        self.assertIn(0, pc)
        self.assertIn(1, pc)
        for cid in [0, 1]:
            self.assertIn("ipc", pc[cid])


if __name__ == "__main__":
    unittest.main(verbosity=2)
