"""
FLUX Fleet Simulator — simulate multi-agent fleet with I2I coordination.

Simulates vessels executing FLUX programs, exchanging messages via I2I,
and coordinating tasks through Tom Sawyer protocol.

Enhanced with:
- Cycle-accurate simulation mode
- 5-stage pipeline simulation (fetch/decode/execute/memory/writeback)
- Branch prediction simulation (bimodal, 2-bit saturating)
- Cache simulation (L1 instruction/data, L2 unified)
- Memory bus contention modeling
- Multi-core simulation (2-4 FLUX cores with shared memory)
- Performance counters (IPC, cache hit rate, branch misprediction rate)
"""
import time
import random
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Callable, Tuple
from enum import Enum


# ═══════════════════════════════════════════════════════════
# Fleet-level types (original)
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


# ═══════════════════════════════════════════════════════════
# CPU-Level Simulation Enhancements
# ═══════════════════════════════════════════════════════════

class PipelineStage(Enum):
    """5-stage pipeline stages."""
    FETCH = "fetch"
    DECODE = "decode"
    EXECUTE = "execute"
    MEMORY = "memory"
    WRITEBACK = "writeback"


# ── Instruction format for pipeline ──────────────────────

@dataclass
class PipelineInstruction:
    """An instruction flowing through the pipeline."""
    pc: int
    opcode: int
    raw_bytes: List[int]
    size: int = 1
    stage: PipelineStage = PipelineStage.FETCH
    result: int = 0
    dest_reg: int = -1
    src_regs: List[int] = field(default_factory=list)
    is_branch: bool = False
    branch_taken: bool = False
    branch_target: int = 0
    predicted_target: int = 0
    mispredicted: bool = False
    is_memory_op: bool = False
    mem_addr: int = 0
    is_load: bool = False
    is_store: bool = False
    stall_cycles: int = 0
    ready: bool = False
    flushed: bool = False


# ── Cache Simulation ────────────────────────────────────

@dataclass
class CacheConfig:
    """Configuration for a cache level."""
    name: str
    size_bytes: int = 256       # total cache size
    line_size: int = 16         # bytes per cache line
    associativity: int = 4      # ways
    hit_latency: int = 1        # cycles for hit
    miss_penalty: int = 10      # cycles for miss


class CacheLine:
    """A single cache line."""
    __slots__ = ['valid', 'dirty', 'tag', 'data', 'last_access']
    
    def __init__(self):
        self.valid = False
        self.dirty = False
        self.tag = 0
        self.data = bytearray()
        self.last_access = 0


class Cache:
    """Simulates a single cache level."""
    
    def __init__(self, config: CacheConfig):
        self.config = config
        self.num_sets = config.size_bytes // (config.line_size * config.associativity)
        self.sets: List[List[CacheLine]] = []
        for _ in range(self.num_sets):
            self.sets.append([CacheLine() for _ in range(config.associativity)])
        self.hits = 0
        self.misses = 0
        self.access_count = 0
    
    def _index(self, addr: int) -> int:
        return (addr // self.config.line_size) % self.num_sets
    
    def _tag(self, addr: int) -> int:
        return addr // (self.config.line_size * self.num_sets)
    
    def access(self, addr: int, write: bool = False) -> int:
        """Access cache. Returns latency (hit_latency or miss_penalty)."""
        self.access_count += 1
        idx = self._index(addr)
        tag = self._tag(addr)
        cache_set = self.sets[idx]
        
        # Check for hit
        for line in cache_set:
            if line.valid and line.tag == tag:
                self.hits += 1
                line.last_access = self.access_count
                if write:
                    line.dirty = True
                return self.config.hit_latency
        
        # Miss: evict LRU
        self.misses += 1
        lru_line = min(cache_set, key=lambda l: l.last_access)
        lru_line.valid = True
        lru_line.tag = tag
        lru_line.data = bytearray(self.config.line_size)
        lru_line.dirty = write
        lru_line.last_access = self.access_count
        return self.config.miss_penalty
    
    def invalidate(self, addr: int):
        """Invalidate a cache line."""
        idx = self._index(addr)
        tag = self._tag(addr)
        for line in self.sets[idx]:
            if line.valid and line.tag == tag:
                line.valid = False
                break
    
    def flush(self):
        """Flush all dirty lines."""
        dirty_count = 0
        for cache_set in self.sets:
            for line in cache_set:
                if line.valid and line.dirty:
                    dirty_count += 1
                    line.dirty = False
        return dirty_count
    
    @property
    def hit_rate(self) -> float:
        if self.access_count == 0:
            return 0.0
        return self.hits / self.access_count
    
    def reset_stats(self):
        self.hits = 0
        self.misses = 0
        self.access_count = 0


class CacheHierarchy:
    """Manages L1I, L1D, and L2 cache hierarchy."""
    
    def __init__(self, l1i_config: CacheConfig = None, l1d_config: CacheConfig = None,
                 l2_config: CacheConfig = None):
        self.l1i = Cache(l1i_config or CacheConfig("L1I", 256, 16, 4, 1, 4))
        self.l1d = Cache(l1d_config or CacheConfig("L1D", 256, 16, 4, 1, 4))
        self.l2 = Cache(l2_config or CacheConfig("L2", 1024, 32, 8, 5, 20))
    
    def instruction_access(self, addr: int) -> int:
        """Access instruction cache; falls through to L2 on miss."""
        latency = self.l1i.access(addr)
        if latency > self.l1i.config.hit_latency:
            latency += self.l2.access(addr)
        return latency
    
    def data_access(self, addr: int, write: bool = False) -> int:
        """Access data cache; falls through to L2 on miss."""
        latency = self.l1d.access(addr, write)
        if latency > self.l1d.config.hit_latency:
            latency += self.l2.access(addr, write)
        return latency
    
    @property
    def l1i_hit_rate(self) -> float:
        return self.l1i.hit_rate
    
    @property
    def l1d_hit_rate(self) -> float:
        return self.l1d.hit_rate
    
    @property
    def l2_hit_rate(self) -> float:
        return self.l2.hit_rate
    
    @property
    def overall_hit_rate(self) -> float:
        total_access = (self.l1i.access_count + self.l1d.access_count)
        if total_access == 0:
            return 0.0
        total_hits = self.l1i.hits + self.l1d.hits
        return total_hits / total_access


# ── Branch Prediction ───────────────────────────────────

class PredictorType(Enum):
    NONE = "none"           # No prediction, always predict not taken
    BIMODAL = "bimodal"     # Bimodal predictor with 2-bit counters
    ALWAYS_TAKEN = "always_taken"
    ALWAYS_NOT_TAKEN = "always_not_taken"


class BranchPredictor:
    """Branch predictor with bimodal 2-bit saturating counters."""
    
    def __init__(self, predictor_type: PredictorType = PredictorType.BIMODAL,
                 table_size: int = 256):
        self.predictor_type = predictor_type
        self.table_size = table_size
        # 2-bit saturating counters: 0=strongly not taken, 1=weakly not taken,
        # 2=weakly taken, 3=strongly taken
        self.counters = [0] * table_size
        self.predictions = 0
        self.correct = 0
        self.mispredictions = 0
    
    def predict(self, pc: int) -> bool:
        """Predict whether branch at pc will be taken."""
        self.predictions += 1
        if self.predictor_type == PredictorType.ALWAYS_TAKEN:
            return True
        elif self.predictor_type == PredictorType.ALWAYS_NOT_TAKEN:
            return False
        elif self.predictor_type == PredictorType.NONE:
            return False
        else:  # BIMODAL
            idx = pc % self.table_size
            return self.counters[idx] >= 2
    
    def update(self, pc: int, actually_taken: bool, predicted: bool = None):
        """Update predictor state after branch resolution.
        
        Args:
            pc: Program counter of the branch.
            actually_taken: Whether the branch was actually taken.
            predicted: The prediction that was made (must be passed by caller
                       to avoid double-counting predictions).
        """
        if predicted is None:
            predicted = self.predict(pc)
        
        if self.predictor_type != PredictorType.BIMODAL:
            if predicted == actually_taken:
                self.correct += 1
            else:
                self.mispredictions += 1
            return
        
        idx = pc % self.table_size
        
        if predicted == actually_taken:
            self.correct += 1
        else:
            self.mispredictions += 1
        
        # Update 2-bit saturating counter
        if actually_taken:
            self.counters[idx] = min(3, self.counters[idx] + 1)
        else:
            self.counters[idx] = max(0, self.counters[idx] - 1)
    
    @property
    def accuracy(self) -> float:
        if self.predictions == 0:
            return 0.0
        return self.correct / self.predictions
    
    @property
    def misprediction_rate(self) -> float:
        if self.predictions == 0:
            return 0.0
        return self.mispredictions / self.predictions
    
    def reset_stats(self):
        self.predictions = 0
        self.correct = 0
        self.mispredictions = 0
        self.counters = [0] * self.table_size


# ── Memory Bus ──────────────────────────────────────────

class MemoryBus:
    """Models memory bus contention between multiple cores."""
    
    def __init__(self, bandwidth_bytes_per_cycle: int = 16, latency: int = 10):
        self.bandwidth = bandwidth_bytes_per_cycle
        self.base_latency = latency
        self.current_cycle = 0
        self.pending_requests: List[Dict] = []
        self.completed_requests = 0
        self.contention_stalls = 0
        self.total_wait_cycles = 0
    
    def request(self, core_id: int, addr: int, size: int = 4, cycle: int = 0) -> int:
        """Request memory access. Returns total latency including contention."""
        self.current_cycle = cycle
        # Check for concurrent requests (contention)
        concurrent = len(self.pending_requests)
        contention_penalty = concurrent * 2  # 2 cycles extra per concurrent request
        
        if contention_penalty > 0:
            self.contention_stalls += 1
            self.total_wait_cycles += contention_penalty
        
        self.pending_requests.append({
            "core_id": core_id, "addr": addr, "size": size,
            "cycle": cycle, "ready_cycle": cycle + self.base_latency + contention_penalty
        })
        
        self.completed_requests += 1
        return self.base_latency + contention_penalty
    
    def advance(self, cycle: int):
        """Advance bus state, completing ready requests."""
        self.current_cycle = cycle
        self.pending_requests = [
            r for r in self.pending_requests if r["ready_cycle"] > cycle
        ]
    
    @property
    def avg_contention_penalty(self) -> float:
        if self.contention_stalls == 0:
            return 0.0
        return self.total_wait_cycles / self.contention_stalls
    
    def reset_stats(self):
        self.pending_requests.clear()
        self.completed_requests = 0
        self.contention_stalls = 0
        self.total_wait_cycles = 0


# ── Performance Counters ────────────────────────────────

@dataclass
class PerformanceCounters:
    """Track various performance metrics during simulation."""
    cycles: int = 0
    instructions_completed: int = 0
    branches_total: int = 0
    branches_taken: int = 0
    branch_mispredictions: int = 0
    cache_hits_l1i: int = 0
    cache_misses_l1i: int = 0
    cache_hits_l1d: int = 0
    cache_misses_l1d: int = 0
    cache_hits_l2: int = 0
    cache_misses_l2: int = 0
    pipeline_stalls: int = 0
    pipeline_flushes: int = 0
    memory_stalls: int = 0
    bus_contention_stalls: int = 0
    
    @property
    def ipc(self) -> float:
        """Instructions per cycle."""
        if self.cycles == 0:
            return 0.0
        return self.instructions_completed / self.cycles
    
    @property
    def branch_misprediction_rate(self) -> float:
        if self.branches_total == 0:
            return 0.0
        return self.branch_mispredictions / self.branches_total
    
    @property
    def l1i_hit_rate(self) -> float:
        total = self.cache_hits_l1i + self.cache_misses_l1i
        return self.cache_hits_l1i / total if total > 0 else 0.0
    
    @property
    def l1d_hit_rate(self) -> float:
        total = self.cache_hits_l1d + self.cache_misses_l1d
        return self.cache_hits_l1d / total if total > 0 else 0.0
    
    @property
    def l2_hit_rate(self) -> float:
        total = self.cache_hits_l2 + self.cache_misses_l2
        return self.cache_hits_l2 / total if total > 0 else 0.0
    
    def snapshot(self) -> Dict:
        return {
            "cycles": self.cycles,
            "instructions_completed": self.instructions_completed,
            "ipc": self.ipc,
            "branches_total": self.branches_total,
            "branch_misprediction_rate": self.branch_misprediction_rate,
            "l1i_hit_rate": self.l1i_hit_rate,
            "l1d_hit_rate": self.l1d_hit_rate,
            "l2_hit_rate": self.l2_hit_rate,
            "pipeline_stalls": self.pipeline_stalls,
            "pipeline_flushes": self.pipeline_flushes,
            "memory_stalls": self.memory_stalls,
        }
    
    def reset(self):
        for attr_name in self.__dataclass_fields__:
            setattr(self, attr_name, 0 if isinstance(getattr(self, attr_name), int) else 0)


# ── Pipeline Simulator ──────────────────────────────────

class PipelineSimulator:
    """5-stage pipeline simulation with hazard detection and forwarding."""
    
    BRANCH_OPS = {0x3C, 0x3D, 0x43, 0x46}
    MEMORY_OPS = {0x0C, 0x0D}  # PUSH, POP
    
    def __init__(self, predictor: BranchPredictor = None,
                 caches: CacheHierarchy = None):
        self.predictor = predictor or BranchPredictor(PredictorType.BIMODAL)
        self.caches = caches or CacheHierarchy()
        self.counters = PerformanceCounters()
        
        # Pipeline registers (one slot per stage)
        self.pipeline: Dict[PipelineStage, Optional[PipelineInstruction]] = {
            PipelineStage.FETCH: None,
            PipelineStage.DECODE: None,
            PipelineStage.EXECUTE: None,
            PipelineStage.MEMORY: None,
            PipelineStage.WRITEBACK: None,
        }
        self.pc = 0
        self.bytecode = bytes()
        self.regs = [0] * 64
        self.stack = [0] * 4096
        self.sp = 4096
        self.halted = False
        self.cycle = 0
    
    def _signed8(self, b):
        return b - 256 if b > 127 else b
    
    def _decode_instruction(self, pc: int) -> PipelineInstruction:
        """Decode instruction at given PC."""
        op = self.bytecode[pc] if pc < len(self.bytecode) else 0x00
        size = 1
        dest_reg = -1
        src_regs = []
        is_branch = False
        is_memory_op = False
        
        if op in (0x08, 0x09, 0x0A, 0x0B):
            size = 2; dest_reg = self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0
        elif op in (0x0C, 0x0D):
            size = 2; dest_reg = self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0
            is_memory_op = True
        elif op == 0x18:
            size = 3; dest_reg = self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0
        elif op in (0x20, 0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27,
                     0x28, 0x29, 0x2A, 0x2B, 0x2C, 0x2D, 0x2E, 0x2F, 0x3A):
            size = 4
            dest_reg = self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0
            src_regs = [
                self.bytecode[pc+2] if pc+2 < len(self.bytecode) else 0,
                self.bytecode[pc+3] if pc+3 < len(self.bytecode) else 0,
            ]
        elif op in (0x3C, 0x3D):
            size = 4
            src_regs = [self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0]
            is_branch = True
        elif op == 0x43:
            size = 4; is_branch = True
        elif op == 0x46:
            size = 4
            src_regs = [self.bytecode[pc+1] if pc+1 < len(self.bytecode) else 0]
            is_branch = True
        
        raw = list(self.bytecode[pc:pc+size]) if pc + size <= len(self.bytecode) else []
        
        return PipelineInstruction(
            pc=pc, opcode=op, raw_bytes=raw, size=size,
            dest_reg=dest_reg, src_regs=src_regs,
            is_branch=is_branch, is_memory_op=is_memory_op,
            is_load=(op == 0x0D), is_store=(op == 0x0C),
        )
    
    def _detect_hazard(self, inst: PipelineInstruction) -> bool:
        """Check for RAW hazards with instructions in later pipeline stages."""
        stages_to_check = [
            PipelineStage.EXECUTE,
            PipelineStage.MEMORY,
            PipelineStage.WRITEBACK,
        ]
        for stage in stages_to_check:
            pending = self.pipeline[stage]
            if pending and not pending.flushed and pending.dest_reg >= 0:
                if pending.dest_reg in inst.src_regs:
                    return True
        return False
    
    def step_cycle(self) -> bool:
        """Execute one pipeline cycle. Returns False if halted and pipeline drained."""
        self.cycle += 1
        self.counters.cycles = self.cycle
        stall = False
        
        # ── WRITEBACK stage ──
        wb_inst = self.pipeline[PipelineStage.WRITEBACK]
        if wb_inst and not wb_inst.flushed:
            if wb_inst.dest_reg >= 0:
                self.regs[wb_inst.dest_reg] = wb_inst.result
            self.counters.instructions_completed += 1
        self.pipeline[PipelineStage.WRITEBACK] = self.pipeline[PipelineStage.MEMORY]
        
        # ── MEMORY stage ──
        mem_inst = self.pipeline[PipelineStage.MEMORY]
        if mem_inst and not mem_inst.flushed:
            if mem_inst.is_load:
                latency = self.caches.data_access(mem_inst.mem_addr)
                self.counters.memory_stalls += max(0, latency - 1)
            elif mem_inst.is_store:
                self.sp -= 1
                self.stack[self.sp] = mem_inst.result
        self.pipeline[PipelineStage.MEMORY] = self.pipeline[PipelineStage.EXECUTE]
        
        # ── EXECUTE stage ──
        ex_inst = self.pipeline[PipelineStage.EXECUTE]
        if ex_inst and not ex_inst.flushed:
            self._execute_instruction(ex_inst)
        old_ex = self.pipeline[PipelineStage.DECODE]
        self.pipeline[PipelineStage.EXECUTE] = old_ex
        
        # ── DECODE stage ──
        dec_inst = old_ex
        if dec_inst and not dec_inst.flushed:
            # Check for RAW hazard with instructions in MEM and WB (which were
            # just shifted from EX and MEM respectively)
            hazard = False
            for stage in (PipelineStage.MEMORY, PipelineStage.WRITEBACK):
                pending = self.pipeline[stage]
                if pending and not pending.flushed and pending.dest_reg >= 0:
                    if pending.dest_reg in dec_inst.src_regs:
                        hazard = True
                        break
            if hazard:
                stall = True
                self.counters.pipeline_stalls += 1
                # Keep instruction in decode, insert bubble into execute
                self.pipeline[PipelineStage.DECODE] = dec_inst
                self.pipeline[PipelineStage.EXECUTE] = None
                # Do NOT touch FETCH — keep the instruction there so it
                # can advance to DECODE when the stall resolves.
                # Handle branch resolution if any
                if ex_inst and ex_inst.is_branch and not ex_inst.flushed:
                    self._resolve_branch(ex_inst)
                return True
        
        self.pipeline[PipelineStage.DECODE] = self.pipeline[PipelineStage.FETCH]
        
        # ── FETCH stage (only if not halted) ──
        if not self.halted and not stall and self.pc < len(self.bytecode):
            # Check instruction cache
            latency = self.caches.instruction_access(self.pc)
            if latency > self.caches.l1i.config.hit_latency:
                self.counters.memory_stalls += latency - self.caches.l1i.config.hit_latency
            
            inst = self._decode_instruction(self.pc)
            inst.stage = PipelineStage.FETCH
            
            # Branch prediction at fetch
            if inst.is_branch:
                predicted_taken = self.predictor.predict(inst.pc)
                inst.predicted_target = inst.pc  # default: not taken
            
            self.pipeline[PipelineStage.FETCH] = inst
            
            # Predict PC for next fetch
            if inst.is_branch and self.predictor.predict(inst.pc):
                # Predicted taken — speculative fetch at branch target
                self._compute_branch_target(inst)
                if inst.branch_target:
                    self.pc = inst.branch_target
                else:
                    self.pc += inst.size
            else:
                self.pc += inst.size
        elif not stall:
            self.pipeline[PipelineStage.FETCH] = None
        
        # Handle branch resolution in execute
        if ex_inst and ex_inst.is_branch and not ex_inst.flushed:
            self._resolve_branch(ex_inst)
        
        return not self.halted
    
    def _resolve_branch(self, ex_inst: PipelineInstruction):
        """Resolve branch in execute stage, handle misprediction."""
        predicted_taken = self.predictor.predict(ex_inst.pc)
        if predicted_taken != ex_inst.branch_taken:
            # Misprediction — flush pipeline
            ex_inst.mispredicted = True
            self.counters.branch_mispredictions += 1
            self.counters.pipeline_flushes += 1
            for s in (PipelineStage.FETCH, PipelineStage.DECODE):
                if self.pipeline[s]:
                    self.pipeline[s].flushed = True
            # Redirect fetch
            if ex_inst.branch_taken and ex_inst.branch_target:
                self.pc = ex_inst.branch_target
            else:
                self.pc = ex_inst.pc + ex_inst.size
        self.counters.branches_total += 1
        if ex_inst.branch_taken:
            self.counters.branches_taken += 1
    
    def _compute_branch_target(self, inst: PipelineInstruction):
        """Compute actual branch target."""
        op = inst.opcode
        if op == 0x3C:  # JZ
            offset = self._signed8(inst.raw_bytes[2]) if len(inst.raw_bytes) > 2 else 0
            inst.branch_target = inst.pc + offset
            inst.branch_taken = self.regs[inst.src_regs[0]] == 0 if inst.src_regs else False
        elif op == 0x3D:  # JNZ
            offset = self._signed8(inst.raw_bytes[2]) if len(inst.raw_bytes) > 2 else 0
            inst.branch_target = inst.pc + offset
            inst.branch_taken = self.regs[inst.src_regs[0]] != 0 if inst.src_regs else True
        elif op == 0x43:  # JMP
            lo = inst.raw_bytes[2] if len(inst.raw_bytes) > 2 else 0
            hi = inst.raw_bytes[3] if len(inst.raw_bytes) > 3 else 0
            v = lo | (hi << 8)
            offset = v - 0x10000 if v > 0x7FFF else v
            inst.branch_target = inst.pc + offset
            inst.branch_taken = True
        elif op == 0x46:  # LOOP
            lo = inst.raw_bytes[2] if len(inst.raw_bytes) > 2 else 0
            hi = inst.raw_bytes[3] if len(inst.raw_bytes) > 3 else 0
            v = lo | (hi << 8)
            offset = v - 0x10000 if v > 0x7FFF else v
            inst.branch_target = inst.pc + offset
            if inst.src_regs:
                self.regs[inst.src_regs[0]] -= 1
                inst.branch_taken = self.regs[inst.src_regs[0]] != 0
            else:
                inst.branch_taken = False
    
    def _execute_instruction(self, inst: PipelineInstruction):
        """Execute instruction and compute result."""
        op = inst.opcode
        regs = self.regs
        
        if op == 0x00:
            self.halted = True
            inst.ready = True
        elif op == 0x08:
            inst.result = regs[inst.dest_reg] + 1
            inst.ready = True
        elif op == 0x09:
            inst.result = regs[inst.dest_reg] - 1
            inst.ready = True
        elif op == 0x18:
            inst.result = self._signed8(inst.raw_bytes[2]) if len(inst.raw_bytes) > 2 else 0
            inst.ready = True
        elif op == 0x20:
            inst.result = regs[inst.src_regs[0]] + regs[inst.src_regs[1]]
            inst.ready = True
        elif op == 0x21:
            inst.result = regs[inst.src_regs[0]] - regs[inst.src_regs[1]]
            inst.ready = True
        elif op == 0x22:
            inst.result = regs[inst.src_regs[0]] * regs[inst.src_regs[1]]
            inst.ready = True
        elif op == 0x2C:
            inst.result = 1 if regs[inst.src_regs[0]] == regs[inst.src_regs[1]] else 0
            inst.ready = True
        elif op == 0x3A:
            inst.result = regs[inst.src_regs[0]]
            inst.ready = True
        elif op in self.BRANCH_OPS:
            self._compute_branch_target(inst)
            inst.ready = True
        elif op == 0x0C:  # PUSH
            inst.mem_addr = self.sp - 1
            inst.result = regs[inst.dest_reg] if inst.dest_reg >= 0 else 0
            inst.ready = True
        elif op == 0x0D:  # POP
            inst.mem_addr = self.sp
            inst.result = self.stack[self.sp] if self.sp < len(self.stack) else 0
            inst.ready = True
        else:
            inst.ready = True
    
    def _to_unsigned_bytes(self, bytecode: List[int]) -> bytes:
        """Convert a list that may contain signed values to unsigned bytes."""
        return bytes(b & 0xFF for b in bytecode)
    
    def load(self, bytecode: List[int], initial_regs: Dict[int, int] = None):
        """Load a program for simulation."""
        self.bytecode = self._to_unsigned_bytes(bytecode)
        self.pc = 0
        self.regs = [0] * 64
        self.stack = [0] * 4096
        self.sp = 4096
        self.halted = False
        self.cycle = 0
        self.counters.reset()
        self.pipeline = {s: None for s in PipelineStage}
        
        if initial_regs:
            for k, v in initial_regs.items():
                self.regs[k] = v
    
    def run(self, max_cycles: int = 10000) -> PerformanceCounters:
        """Run until halted or max cycles."""
        while self.cycle < max_cycles:
            active = self.step_cycle()
            if self.halted:
                # Drain remaining pipeline instructions
                for _ in range(5):
                    self.step_cycle()
                break
        
        return self.counters
    
    def get_registers(self) -> Dict[int, int]:
        return {i: self.regs[i] for i in range(16)}


# ── Single FLUX Core (cycle-accurate) ───────────────────

class FluxCore:
    """A single FLUX CPU core with pipeline, predictor, and caches."""
    
    def __init__(self, core_id: int = 0,
                 predictor_type: PredictorType = PredictorType.BIMODAL,
                 cache_config: Dict = None):
        self.core_id = core_id
        self.predictor = BranchPredictor(predictor_type)
        
        if cache_config:
            cc = cache_config
            caches = CacheHierarchy(
                CacheConfig("L1I", cc.get("l1i_size", 256), 16, 4, 1, 4),
                CacheConfig("L1D", cc.get("l1d_size", 256), 16, 4, 1, 4),
                CacheConfig("L2", cc.get("l2_size", 1024), 32, 8, 5, 20),
            )
        else:
            caches = CacheHierarchy()
        
        self.pipeline = PipelineSimulator(self.predictor, caches)
        self.regs = self.pipeline.regs
    
    def load(self, bytecode: List[int], initial_regs: Dict[int, int] = None):
        self.pipeline.load(bytecode, initial_regs)
        self.regs = self.pipeline.regs  # update reference after pipeline resets regs
    
    def step(self) -> bool:
        was_halted = self.is_halted
        result = self.pipeline.step_cycle()
        # When core first halts, drain remaining pipeline stages
        if self.is_halted and not was_halted:
            for _ in range(5):
                self.pipeline.step_cycle()
        return result
    
    def run(self, max_cycles: int = 10000) -> PerformanceCounters:
        return self.pipeline.run(max_cycles)
    
    def get_registers(self) -> Dict[int, int]:
        return self.pipeline.get_registers()
    
    @property
    def counters(self) -> PerformanceCounters:
        return self.pipeline.counters
    
    @property
    def is_halted(self) -> bool:
        return self.pipeline.halted


# ── Multi-Core Simulator ────────────────────────────────

class CoreState(Enum):
    IDLE = "idle"
    RUNNING = "running"
    WAITING_BUS = "waiting_bus"
    HALTED = "halted"


@dataclass
class MultiCoreConfig:
    num_cores: int = 2
    shared_memory_size: int = 65536
    bus_bandwidth: int = 16
    bus_latency: int = 10
    predictor_type: PredictorType = PredictorType.BIMODAL
    l1i_size: int = 256
    l1d_size: int = 256
    l2_size: int = 1024


class MultiCoreSimulator:
    """Simulates 2-4 FLUX cores with shared memory and bus contention."""
    
    def __init__(self, config: MultiCoreConfig = None):
        self.config = config or MultiCoreConfig()
        if not (2 <= self.config.num_cores <= 4):
            raise ValueError("num_cores must be between 2 and 4")
        
        self.shared_memory = [0] * self.config.shared_memory_size
        self.bus = MemoryBus(self.config.bus_bandwidth, self.config.bus_latency)
        self.cycle = 0
        
        self.cores: List[FluxCore] = []
        self.core_states: List[CoreState] = []
        for i in range(self.config.num_cores):
            core = FluxCore(
                core_id=i,
                predictor_type=self.config.predictor_type,
                cache_config={
                    "l1i_size": self.config.l1i_size,
                    "l1d_size": self.config.l1d_size,
                    "l2_size": self.config.l2_size,
                }
            )
            self.cores.append(core)
            self.core_states.append(CoreState.IDLE)
        
        self.event_log: List[str] = []
    
    def load_program(self, core_id: int, bytecode: List[int],
                     initial_regs: Dict[int, int] = None,
                     mem_offset: int = 0):
        """Load a program onto a specific core."""
        if core_id < 0 or core_id >= self.config.num_cores:
            raise ValueError(f"Invalid core_id: {core_id}")
        
        # Copy bytecode into shared memory
        for i, b in enumerate(bytecode):
            self.shared_memory[mem_offset + i] = b
        
        self.cores[core_id].load(bytecode, initial_regs)
        self.core_states[core_id] = CoreState.RUNNING
        self._log(f"Core {core_id}: loaded program ({len(bytecode)} bytes)")
    
    def write_shared_memory(self, addr: int, value: int, core_id: int = -1):
        """Write to shared memory with bus transaction."""
        if addr < 0 or addr >= self.config.shared_memory_size:
            raise ValueError(f"Address {addr} out of range")
        latency = self.bus.request(core_id, addr, 4, self.cycle)
        self.shared_memory[addr] = value
        # Invalidate caches on other cores (simplified coherence)
        for i, core in enumerate(self.cores):
            if i != core_id:
                core.pipeline.caches.l1d.invalidate(addr)
                core.pipeline.caches.l2.invalidate(addr)
        self._log(f"Core {core_id}: write [{addr}] = {value} (latency: {latency})")
    
    def read_shared_memory(self, addr: int, core_id: int = -1) -> Tuple[int, int]:
        """Read from shared memory with bus transaction. Returns (value, latency)."""
        if addr < 0 or addr >= self.config.shared_memory_size:
            raise ValueError(f"Address {addr} out of range")
        latency = self.bus.request(core_id, addr, 4, self.cycle)
        value = self.shared_memory[addr]
        return value, latency
    
    def step(self) -> bool:
        """Execute one cycle across all cores. Returns False if all halted."""
        self.cycle += 1
        any_active = False
        
        for i, core in enumerate(self.cores):
            if self.core_states[i] == CoreState.RUNNING:
                was_halted = core.is_halted
                core.step()
                
                if core.is_halted and not was_halted:
                    self.core_states[i] = CoreState.HALTED
                    self._log(f"Core {i}: halted at cycle {self.cycle}")
                else:
                    any_active = True
        
        self.bus.advance(self.cycle)
        return any_active
    
    def run(self, max_cycles: int = 10000) -> Dict:
        """Run all cores until all halt or max cycles."""
        for _ in range(max_cycles):
            if not self.step():
                break
        
        return self.status()
    
    def status(self) -> Dict:
        core_summaries = []
        total_ipc = 0.0
        for i, core in enumerate(self.cores):
            counters = core.counters
            core_summaries.append({
                "core_id": i,
                "state": self.core_states[i].value,
                "cycles": counters.cycles,
                "instructions": counters.instructions_completed,
                "ipc": counters.ipc,
                "branch_misprediction_rate": counters.branch_misprediction_rate,
                "l1i_hit_rate": counters.l1i_hit_rate,
                "l1d_hit_rate": counters.l1d_hit_rate,
                "l2_hit_rate": counters.l2_hit_rate,
                "pipeline_stalls": counters.pipeline_stalls,
                "pipeline_flushes": counters.pipeline_flushes,
            })
            total_ipc += counters.ipc
        
        return {
            "total_cycles": self.cycle,
            "num_cores": self.config.num_cores,
            "aggregate_ipc": total_ipc,
            "bus_contention_stalls": self.bus.contention_stalls,
            "avg_bus_contention_penalty": self.bus.avg_contention_penalty,
            "cores": core_summaries,
            "event_log": self.event_log[-20:],
        }
    
    def _log(self, msg: str):
        self.event_log.append(f"[c{self.cycle}] {msg}")


# ── Cycle-Accurate Simulator (wrapper) ──────────────────

class CycleAccurateSimulator:
    """High-level cycle-accurate simulation interface."""
    
    def __init__(self, predictor_type: PredictorType = PredictorType.BIMODAL,
                 trace: bool = False):
        self.core = FluxCore(0, predictor_type)
        self.trace = trace
        self.trace_log: List[str] = []
    
    def simulate(self, bytecode: List[int], max_cycles: int = 10000,
                 initial_regs: Dict[int, int] = None) -> Dict:
        """Run cycle-accurate simulation and return results."""
        self.core.load(bytecode, initial_regs)
        self.trace_log.clear()
        
        if self.trace:
            while not self.core.is_halted and self.core.counters.cycles < max_cycles:
                self.core.step()
                self._trace_cycle()
            # Drain pipeline
            for _ in range(5):
                if not self.core.step():
                    break
                self._trace_cycle()
        else:
            self.core.run(max_cycles)
        
        counters = self.core.counters
        return {
            "registers": self.core.get_registers(),
            "cycles": counters.cycles,
            "instructions": counters.instructions_completed,
            "ipc": counters.ipc,
            "branch_misprediction_rate": counters.branch_misprediction_rate,
            "l1i_hit_rate": counters.l1i_hit_rate,
            "l1d_hit_rate": counters.l1d_hit_rate,
            "l2_hit_rate": counters.l2_hit_rate,
            "pipeline_stalls": counters.pipeline_stalls,
            "pipeline_flushes": counters.pipeline_flushes,
            "memory_stalls": counters.memory_stalls,
            "trace": self.trace_log if self.trace else None,
        }
    
    def _trace_cycle(self):
        counters = self.core.counters
        pc = self.core.pipeline.pc
        halted = self.core.is_halted
        self.trace_log.append(
            f"cycle={counters.cycles} pc={pc} ipc={counters.ipc:.3f} halted={halted}"
        )


# ═══════════════════════════════════════════════════════════
# Tests
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


# ── CPU Enhancement Tests ───────────────────────────────

class TestCache(unittest.TestCase):
    """Tests for cache simulation."""
    
    def test_cache_creation(self):
        cache = Cache(CacheConfig("L1I", 256, 16, 4, 1, 10))
        self.assertEqual(cache.config.name, "L1I")
        self.assertEqual(cache.num_sets, 4)  # 256 / (16 * 4)
    
    def test_cache_hit(self):
        cache = Cache(CacheConfig("L1I", 256, 16, 4, 1, 10))
        cache.access(0)  # miss (cold)
        latency = cache.access(0)  # hit
        self.assertEqual(latency, 1)
        self.assertEqual(cache.hits, 1)
        self.assertEqual(cache.misses, 1)
    
    def test_cache_miss(self):
        cache = Cache(CacheConfig("L1D", 256, 16, 4, 1, 10))
        latency = cache.access(0)
        self.assertEqual(latency, 10)
        self.assertEqual(cache.misses, 1)
    
    def test_cache_hit_rate(self):
        cache = Cache(CacheConfig("L1", 256, 16, 4, 1, 10))
        cache.access(0)   # miss
        cache.access(0)   # hit
        cache.access(16)  # miss (different line)
        cache.access(16)  # hit
        self.assertAlmostEqual(cache.hit_rate, 0.5)
    
    def test_cache_write_dirty(self):
        cache = Cache(CacheConfig("L1D", 256, 16, 4, 1, 10))
        cache.access(0, write=True)  # miss + write
        dirty = cache.flush()
        self.assertGreater(dirty, 0)
    
    def test_cache_invalidate(self):
        cache = Cache(CacheConfig("L1", 256, 16, 4, 1, 10))
        cache.access(0)
        cache.invalidate(0)
        latency = cache.access(0)
        self.assertEqual(latency, 10)  # miss after invalidation
    
    def test_cache_reset_stats(self):
        cache = Cache(CacheConfig("L1", 256, 16, 4, 1, 10))
        cache.access(0)
        cache.reset_stats()
        self.assertEqual(cache.hits, 0)
        self.assertEqual(cache.misses, 0)
    
    def test_cache_hierarchy(self):
        hierarchy = CacheHierarchy()
        latency = hierarchy.instruction_access(0)
        # L1 miss + L2 miss = 1 + 5 = 6 at minimum
        self.assertGreaterEqual(latency, 1)
        self.assertIn("L1I", hierarchy.l1i.config.name)


class TestBranchPredictor(unittest.TestCase):
    """Tests for branch prediction."""
    
    def test_bimodal_creation(self):
        bp = BranchPredictor(PredictorType.BIMODAL, 256)
        self.assertEqual(len(bp.counters), 256)
    
    def test_bimodal_initial_predict_not_taken(self):
        bp = BranchPredictor(PredictorType.BIMODAL)
        self.assertFalse(bp.predict(100))
    
    def test_bimodal_update_taken(self):
        bp = BranchPredictor(PredictorType.BIMODAL)
        bp.update(100, True)
        bp.update(100, True)
        self.assertTrue(bp.predict(100))  # 2 bits = taken
    
    def test_bimodal_accuracy(self):
        bp = BranchPredictor(PredictorType.BIMODAL)
        # Always-taken branch: after warm-up, predictor should learn
        for _ in range(20):
            predicted = bp.predict(50)
            bp.update(50, True, predicted)
        self.assertGreater(bp.accuracy, 0.5)
    
    def test_bimodal_misprediction_rate(self):
        bp = BranchPredictor(PredictorType.BIMODAL)
        for _ in range(10):
            predicted = bp.predict(200)
            bp.update(200, True, predicted)
            predicted = bp.predict(200)
            bp.update(200, False, predicted)  # alternating = hard for 2-bit
        self.assertGreater(bp.misprediction_rate, 0.0)
    
    def test_bimodal_2bit_saturating(self):
        """2-bit counter saturates at 0 and 3."""
        bp = BranchPredictor(PredictorType.BIMODAL)
        idx = 0
        # Saturate at 3
        for _ in range(10):
            bp.update(0, True)
        self.assertEqual(bp.counters[idx], 3)
        # Saturate at 0
        for _ in range(10):
            bp.update(0, False)
        self.assertEqual(bp.counters[idx], 0)
    
    def test_always_taken_predictor(self):
        bp = BranchPredictor(PredictorType.ALWAYS_TAKEN)
        self.assertTrue(bp.predict(0))
    
    def test_always_not_taken_predictor(self):
        bp = BranchPredictor(PredictorType.ALWAYS_NOT_TAKEN)
        self.assertFalse(bp.predict(0))
    
    def test_reset_stats(self):
        bp = BranchPredictor(PredictorType.BIMODAL)
        bp.update(100, True)
        bp.reset_stats()
        self.assertEqual(bp.predictions, 0)


class TestPipeline(unittest.TestCase):
    """Tests for pipeline simulation."""
    
    def test_pipeline_creation(self):
        pipe = PipelineSimulator()
        for stage in PipelineStage:
            self.assertIsNone(pipe.pipeline[stage])
    
    def test_pipeline_load(self):
        pipe = PipelineSimulator()
        pipe.load([0x18, 0, 42, 0x00])
        self.assertEqual(pipe.pc, 0)
        self.assertFalse(pipe.halted)
    
    def test_pipeline_simple_program(self):
        pipe = PipelineSimulator()
        pipe.load([0x18, 0, 42, 0x00])
        counters = pipe.run()
        self.assertEqual(pipe.regs[0], 42)
        self.assertGreater(counters.instructions_completed, 0)
        self.assertGreater(counters.cycles, 0)
    
    def test_pipeline_ipc(self):
        pipe = PipelineSimulator()
        # Simple sequential program for good IPC
        bc = [0x18, 0, 1, 0x18, 1, 2, 0x18, 2, 3, 0x18, 3, 4, 0x00]
        pipe.load(bc)
        counters = pipe.run()
        self.assertGreater(counters.ipc, 0.0)
        self.assertLessEqual(counters.ipc, 1.0)  # single-issue
    
    def test_pipeline_with_loop(self):
        pipe = PipelineSimulator()
        # Count down: R0=5, R1=0, loop: INC R1, DEC R0, JNZ R0 back to INC
        # JNZ at offset 10, INC at offset 6, so offset = 6 - 10 = -4 (0xFC)
        bc = [0x18, 0, 5, 0x18, 1, 0,  # MOVI R0,5; MOVI R1,0
              0x08, 1,                    # INC R1
              0x09, 0,                    # DEC R0
              0x3D, 0, 0xFC,             # JNZ R0, -4 (jump back to INC R1)
              0x00]                       # HALT
        pipe.load(bc)
        counters = pipe.run()
        self.assertEqual(pipe.regs[1], 5)
        self.assertGreater(counters.branches_total, 0)
    
    def test_pipeline_hazard_detection(self):
        pipe = PipelineSimulator()
        # ADD R0, R1, R2 followed by SUB R3, R0, R4 — RAW hazard
        bc = [0x18, 1, 10, 0x18, 2, 20,
              0x20, 0, 1, 2,  # ADD R0, R1, R2
              0x21, 3, 0, 2,  # SUB R3, R0, R2 (depends on R0)
              0x00]
        pipe.load(bc)
        counters = pipe.run()
        self.assertEqual(pipe.regs[0], 30)
        self.assertEqual(pipe.regs[3], 10)


class TestPerformanceCounters(unittest.TestCase):
    """Tests for performance counters."""
    
    def test_counters_creation(self):
        pc = PerformanceCounters()
        self.assertEqual(pc.cycles, 0)
        self.assertEqual(pc.ipc, 0.0)
    
    def test_counters_ipc(self):
        pc = PerformanceCounters()
        pc.cycles = 100
        pc.instructions_completed = 50
        self.assertAlmostEqual(pc.ipc, 0.5)
    
    def test_counters_branch_misprediction_rate(self):
        pc = PerformanceCounters()
        pc.branches_total = 100
        pc.branch_mispredictions = 20
        self.assertAlmostEqual(pc.branch_misprediction_rate, 0.2)
    
    def test_counters_cache_hit_rates(self):
        pc = PerformanceCounters()
        pc.cache_hits_l1i = 80
        pc.cache_misses_l1i = 20
        self.assertAlmostEqual(pc.l1i_hit_rate, 0.8)
    
    def test_counters_snapshot(self):
        pc = PerformanceCounters()
        pc.cycles = 42
        snap = pc.snapshot()
        self.assertEqual(snap["cycles"], 42)
        self.assertIn("ipc", snap)
    
    def test_counters_reset(self):
        pc = PerformanceCounters()
        pc.cycles = 999
        pc.instructions_completed = 500
        pc.reset()
        self.assertEqual(pc.cycles, 0)
        self.assertEqual(pc.instructions_completed, 0)


class TestMemoryBus(unittest.TestCase):
    """Tests for memory bus contention."""
    
    def test_bus_creation(self):
        bus = MemoryBus(16, 10)
        self.assertEqual(bus.base_latency, 10)
    
    def test_bus_single_request(self):
        bus = MemoryBus(16, 10)
        latency = bus.request(0, 0)
        self.assertEqual(latency, 10)  # No contention
    
    def test_bus_contention(self):
        bus = MemoryBus(16, 10)
        bus.request(0, 0)     # pending
        latency = bus.request(1, 4)   # contention
        self.assertGreater(latency, 10)
    
    def test_bus_advance(self):
        bus = MemoryBus(16, 10)
        bus.request(0, 0, cycle=0)
        bus.advance(100)
        self.assertEqual(len(bus.pending_requests), 0)
    
    def test_bus_avg_contention_penalty(self):
        bus = MemoryBus(16, 10)
        bus.request(0, 0)
        bus.request(1, 4)
        self.assertGreater(bus.avg_contention_penalty, 0.0)
    
    def test_bus_reset(self):
        bus = MemoryBus(16, 10)
        bus.request(0, 0)
        bus.reset_stats()
        self.assertEqual(bus.completed_requests, 0)


class TestFluxCore(unittest.TestCase):
    """Tests for single FLUX core."""
    
    def test_core_creation(self):
        core = FluxCore(0)
        self.assertEqual(core.core_id, 0)
    
    def test_core_simple(self):
        core = FluxCore(0)
        core.load([0x18, 0, 99, 0x00])
        counters = core.run()
        self.assertEqual(core.regs[0], 99)
        self.assertGreater(counters.instructions_completed, 0)
    
    def test_core_with_predictor(self):
        core = FluxCore(0, PredictorType.ALWAYS_TAKEN)
        core.load([0x18, 0, 42, 0x00])
        core.run()
        self.assertEqual(core.regs[0], 42)
    
    def test_core_halted(self):
        core = FluxCore(0)
        core.load([0x00])
        core.run()
        self.assertTrue(core.is_halted)
    
    def test_core_get_registers(self):
        core = FluxCore(0)
        core.load([0x18, 0, 7, 0x00])
        core.run()
        regs = core.get_registers()
        self.assertEqual(regs[0], 7)


class TestMultiCoreSimulator(unittest.TestCase):
    """Tests for multi-core simulation."""
    
    def test_multicore_creation(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        self.assertEqual(len(sim.cores), 2)
    
    def test_multicore_invalid_cores(self):
        with self.assertRaises(ValueError):
            MultiCoreSimulator(MultiCoreConfig(num_cores=1))
        with self.assertRaises(ValueError):
            MultiCoreSimulator(MultiCoreConfig(num_cores=8))
    
    def test_multicore_load_and_run(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        sim.load_program(0, [0x18, 0, 10, 0x00])
        sim.load_program(1, [0x18, 0, 20, 0x00])
        result = sim.run()
        self.assertEqual(sim.cores[0].regs[0], 10)
        self.assertEqual(sim.cores[1].regs[0], 20)
    
    def test_multicore_4_cores(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=4))
        for i in range(4):
            sim.load_program(i, [0x18, 0, i + 1, 0x00])
        result = sim.run()
        self.assertEqual(len(result["cores"]), 4)
    
    def test_multicore_shared_memory(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        sim.write_shared_memory(0, 42, core_id=0)
        val, _ = sim.read_shared_memory(0, core_id=1)
        self.assertEqual(val, 42)
    
    def test_multicore_shared_memory_out_of_range(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        with self.assertRaises(ValueError):
            sim.write_shared_memory(999999, 0)
    
    def test_multicore_status(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        status = sim.status()
        self.assertEqual(status["num_cores"], 2)
        self.assertIn("cores", status)
        self.assertIn("aggregate_ipc", status)
    
    def test_multicore_bus_contention(self):
        sim = MultiCoreSimulator(MultiCoreConfig(num_cores=2))
        sim.load_program(0, [0x18, 0, 1, 0x00])
        sim.load_program(1, [0x18, 0, 2, 0x00])
        sim.write_shared_memory(0, 10, core_id=0)
        sim.write_shared_memory(4, 20, core_id=1)
        self.assertGreater(sim.bus.contention_stalls, 0)


class TestCycleAccurateSimulator(unittest.TestCase):
    """Tests for cycle-accurate simulation wrapper."""
    
    def test_simulate_simple(self):
        cas = CycleAccurateSimulator()
        result = cas.simulate([0x18, 0, 42, 0x00])
        self.assertEqual(result["registers"][0], 42)
        self.assertGreater(result["cycles"], 0)
    
    def test_simulate_with_trace(self):
        cas = CycleAccurateSimulator(trace=True)
        result = cas.simulate([0x18, 0, 5, 0x00])
        self.assertIsNotNone(result["trace"])
        self.assertGreater(len(result["trace"]), 0)
    
    def test_simulate_loop(self):
        cas = CycleAccurateSimulator(PredictorType.BIMODAL)
        # JNZ at offset 10, INC at offset 6, offset = -4 (0xFC)
        bc = [0x18, 0, 3, 0x18, 1, 0,
              0x08, 1, 0x09, 0, 0x3D, 0, 0xFC, 0x00]
        result = cas.simulate(bc)
        self.assertEqual(result["registers"][1], 3)
    
    def test_simulate_no_trace(self):
        cas = CycleAccurateSimulator(trace=False)
        result = cas.simulate([0x18, 0, 1, 0x00])
        self.assertIsNone(result["trace"])
    
    def test_simulate_returns_all_metrics(self):
        cas = CycleAccurateSimulator()
        result = cas.simulate([0x18, 0, 1, 0x00])
        expected_keys = {"registers", "cycles", "instructions", "ipc",
                        "branch_misprediction_rate", "l1i_hit_rate",
                        "l1d_hit_rate", "l2_hit_rate", "pipeline_stalls"}
        self.assertTrue(expected_keys.issubset(result.keys()))


if __name__ == "__main__":
    unittest.main(verbosity=2)
