"""
Comprehensive pytest tests for flux-simulator.

Covers: VesselState, MessageType, Message, Task, VesselConfig,
        SimulatedVessel (execution, mailbox, state management),
        FleetSimulator (fleet management, task dispatch, Tom Sawyer protocol,
        step/run logic, status reporting, event logging).
"""
import pytest
from simulator import (
    VesselState,
    MessageType,
    Message,
    Task,
    VesselConfig,
    SimulatedVessel,
    FleetSimulator,
)


# ── VesselState & MessageType Enums ──────────────────────────────────────

class TestVesselState:
    def test_all_states_exist(self):
        expected = {"idle", "running", "waiting", "comms", "halted"}
        actual = {s.value for s in VesselState}
        assert actual == expected

    def test_state_values_are_strings(self):
        for state in VesselState:
            assert isinstance(state.value, str)


class TestMessageType:
    def test_all_types_exist(self):
        expected = {"task", "result", "beacon", "fence", "claim",
                    "complete", "handshake", "bottle"}
        actual = {t.value for t in MessageType}
        assert actual == expected


# ── Message ───────────────────────────────────────────────────────────────

class TestMessage:
    def test_create_message(self):
        msg = Message("alice", "bob", MessageType.TASK, {"key": "val"})
        assert msg.sender == "alice"
        assert msg.recipient == "bob"
        assert msg.msg_type == MessageType.TASK
        assert msg.payload == {"key": "val"}

    def test_timestamp_auto_set(self):
        msg = Message("a", "b", MessageType.BEACON, {})
        assert msg.timestamp > 0

    def test_explicit_timestamp(self):
        msg = Message("a", "b", MessageType.BEACON, {}, timestamp=1234.5)
        assert msg.timestamp == 1234.5

    def test_all_message_types(self):
        for mt in MessageType:
            msg = Message("a", "b", mt, {})
            assert msg.msg_type == mt

    def test_empty_payload(self):
        msg = Message("a", "b", MessageType.FENCE, {})
        assert msg.payload == {}


# ── Task ──────────────────────────────────────────────────────────────────

class TestTask:
    def test_create_task(self):
        t = Task("t1", "desc", [0x18, 0, 42, 0x00], 3)
        assert t.task_id == "t1"
        assert t.description == "desc"
        assert t.bytecode == [0x18, 0, 42, 0x00]
        assert t.difficulty == 3
        assert t.assigned_to is None
        assert t.completed is False
        assert t.result is None
        assert t.fence_id is None

    def test_task_difficulty_range(self):
        for d in range(1, 6):
            t = Task(f"t{d}", f"diff {d}", [], d)
            assert t.difficulty == d

    def test_task_with_assignment(self):
        t = Task("t1", "desc", [], 1, assigned_to="worker1")
        assert t.assigned_to == "worker1"

    def test_task_with_fence(self):
        t = Task("t1", "desc", [], 1, fence_id="fence_abc")
        assert t.fence_id == "fence_abc"


# ── VesselConfig ──────────────────────────────────────────────────────────

class TestVesselConfig:
    def test_defaults(self):
        cfg = VesselConfig("v1", "vessel")
        assert cfg.name == "v1"
        assert cfg.vessel_type == "vessel"
        assert cfg.max_regs == 64
        assert cfg.max_stack == 4096
        assert cfg.speed == 1.0
        assert cfg.capabilities == []

    def test_custom_values(self):
        cfg = VesselConfig(
            "scout1", "scout",
            max_regs=128, max_stack=8192,
            speed=2.5, capabilities=["scan", "report"]
        )
        assert cfg.max_regs == 128
        assert cfg.max_stack == 8192
        assert cfg.speed == 2.5
        assert cfg.capabilities == ["scan", "report"]

    def test_vessel_types(self):
        for vtype in ["lighthouse", "vessel", "scout", "barnacle"]:
            cfg = VesselConfig(f"{vtype}1", vtype)
            assert cfg.vessel_type == vtype


# ── SimulatedVessel ───────────────────────────────────────────────────────

class TestSimulatedVessel:
    def _make_vessel(self, name="v1", vtype="vessel", **kwargs):
        return SimulatedVessel(VesselConfig(name, vtype, **kwargs))

    def test_initial_state(self):
        v = self._make_vessel()
        assert v.state == VesselState.IDLE
        assert v.pc == 0
        assert v.cycles == 0
        assert v.mailbox == []
        assert v.completed_tasks == []
        assert v.merit_badges == []
        assert len(v.regs) == 64
        assert len(v.stack) == 4096
        assert v.sp == 4096

    def test_halt_opcode(self):
        """0x00 should halt execution immediately."""
        v = self._make_vessel()
        result = v.execute([0x00])
        assert v.state == VesselState.IDLE
        assert all(val == 0 for val in result.values())

    def test_movi_loads_value(self):
        """MOVI: loads a signed byte into a register."""
        v = self._make_vessel()
        result = v.execute([0x18, 0, 42, 0x00])
        assert result[0] == 42

    def test_movi_negative(self):
        """MOVI with value > 127 should be interpreted as negative."""
        v = self._make_vessel()
        result = v.execute([0x18, 0, 200, 0x00])
        # 200 - 256 = -56
        assert result[0] == -56

    def test_inc(self):
        """INC should increment a register."""
        v = self._make_vessel()
        result = v.execute([0x18, 0, 5, 0x08, 0, 0x00])
        assert result[0] == 6

    def test_dec(self):
        """DEC should decrement a register."""
        v = self._make_vessel()
        result = v.execute([0x18, 0, 5, 0x09, 0, 0x00])
        assert result[0] == 4

    def test_add(self):
        """ADD Rdst, Rsrc1, Rsrc2."""
        v = self._make_vessel()
        # MOVI R0, 10; MOVI R1, 20; ADD R2, R0, R1; HALT
        result = v.execute([
            0x18, 0, 10,
            0x18, 1, 20,
            0x20, 2, 0, 1,
            0x00
        ])
        assert result[2] == 30

    def test_sub(self):
        """SUB Rdst, Rsrc1, Rsrc2."""
        v = self._make_vessel()
        result = v.execute([
            0x18, 0, 30,
            0x18, 1, 12,
            0x21, 2, 0, 1,
            0x00
        ])
        assert result[2] == 18

    def test_mul(self):
        """MUL Rdst, Rsrc1, Rsrc2."""
        v = self._make_vessel()
        result = v.execute([
            0x18, 0, 6,
            0x18, 1, 7,
            0x22, 2, 0, 1,
            0x00
        ])
        assert result[2] == 42

    def test_cmp_eq_true(self):
        """CMP_EQ should return 1 when equal."""
        v = self._make_vessel()
        result = v.execute([
            0x18, 0, 10,
            0x18, 1, 10,
            0x2C, 2, 0, 1,
            0x00
        ])
        assert result[2] == 1

    def test_cmp_eq_false(self):
        """CMP_EQ should return 0 when not equal."""
        v = self._make_vessel()
        result = v.execute([
            0x18, 0, 10,
            0x18, 1, 20,
            0x2C, 2, 0, 1,
            0x00
        ])
        assert result[2] == 0

    def test_mov_register(self):
        """MOV Rdst, Rsrc, Rsrc."""
        v = self._make_vessel()
        result = v.execute([
            0x18, 0, 99,
            0x3A, 1, 0, 0,
            0x00
        ])
        assert result[1] == 99

    def test_push_pop(self):
        """PUSH then POP should preserve value."""
        v = self._make_vessel()
        # MOVI R0, 42; PUSH R0; POP R1; HALT
        result = v.execute([
            0x18, 0, 42,
            0x0C, 0,
            0x0D, 1,
            0x00
        ])
        assert result[0] == 42  # R0 unchanged
        assert result[1] == 42  # R1 gets popped value

    def test_initial_registers(self):
        """Test pre-loading registers via initial dict."""
        v = self._make_vessel()
        result = v.execute([0x20, 2, 0, 1, 0x00], initial={0: 10, 1: 7})
        assert result[2] == 17

    def test_max_cycles(self):
        """Execution should stop at max_cycles."""
        v = self._make_vessel()
        # Infinite loop (no HALT) should be capped
        result = v.execute([0x18, 0, 1, 0x18, 1, 1], max_cycles=10)
        # Should return without error; cycles should be capped
        assert v.cycles <= 10

    def test_speed_affects_cycles(self):
        """Higher speed allows more effective cycles."""
        v_slow = self._make_vessel("slow", speed=0.5)
        v_fast = self._make_vessel("fast", speed=2.0)
        v_slow.execute([0x18, 0, 1], max_cycles=100)
        v_fast.execute([0x18, 0, 1], max_cycles=100)
        assert v_fast.cycles >= v_slow.cycles

    def test_state_transitions(self):
        v = self._make_vessel()
        assert v.state == VesselState.IDLE
        v.execute([0x18, 0, 42, 0x00])
        assert v.state == VesselState.IDLE  # back to idle after execution

    def test_result_keys(self):
        """Result dict should contain at least keys 0-15."""
        v = self._make_vessel()
        result = v.execute([0x00])
        for i in range(16):
            assert i in result

    def test_unknown_opcode_skipped(self):
        """Unknown opcodes should be skipped (pc += 1)."""
        v = self._make_vessel()
        # 0xFF is unknown, should be skipped, then MOVI should still work
        result = v.execute([0xFF, 0x18, 0, 77, 0x00])
        assert result[0] == 77


# ── SimulatedVessel Mailbox ──────────────────────────────────────────────

class TestVesselMailbox:
    def _make_vessel(self, name="v1"):
        return SimulatedVessel(VesselConfig(name, "vessel"))

    def test_send_creates_message(self):
        v = self._make_vessel("alice")
        msg = v.send("bob", MessageType.HANDSHAKE, {"greeting": "hello"})
        assert msg.sender == "alice"
        assert msg.recipient == "bob"
        assert msg.msg_type == MessageType.HANDSHAKE

    def test_receive_adds_to_mailbox(self):
        v = self._make_vessel()
        msg = Message("sender", "v1", MessageType.BEACON, {})
        v.receive(msg)
        assert len(v.mailbox) == 1

    def test_receive_multiple(self):
        v = self._make_vessel()
        for i in range(5):
            v.receive(Message(f"sender{i}", "v1", MessageType.BEACON, {}))
        assert len(v.mailbox) == 5

    def test_process_mailbox_clears(self):
        v = self._make_vessel()
        v.receive(Message("s", "v1", MessageType.TASK, {}))
        v.receive(Message("s", "v1", MessageType.RESULT, {}))
        msgs = v.process_mailbox()
        assert len(msgs) == 2
        assert v.mailbox == []  # cleared

    def test_process_mailbox_sets_comms_state(self):
        v = self._make_vessel()
        v.receive(Message("s", "v1", MessageType.BEACON, {}))
        v.process_mailbox()
        assert v.state == VesselState.COMMS

    def test_process_empty_mailbox(self):
        v = self._make_vessel()
        msgs = v.process_mailbox()
        assert msgs == []
        assert v.state == VesselState.COMMS


# ── FleetSimulator ────────────────────────────────────────────────────────

class TestFleetSimulator:
    def _make_sim(self):
        return FleetSimulator()

    def test_empty_fleet(self):
        sim = self._make_sim()
        assert sim.vessels == {}
        assert sim.tasks == {}
        assert sim.message_queue == []
        assert sim.tick == 0
        assert sim.event_log == []

    def test_add_vessel(self):
        sim = self._make_sim()
        sim.add_vessel(VesselConfig("oracle1", "lighthouse"))
        assert "oracle1" in sim.vessels
        assert sim.vessels["oracle1"].config.vessel_type == "lighthouse"

    def test_add_multiple_vessels(self):
        sim = self._make_sim()
        names = ["v1", "v2", "v3"]
        for n in names:
            sim.add_vessel(VesselConfig(n, "vessel"))
        assert len(sim.vessels) == 3

    def test_add_vessel_logs(self):
        sim = self._make_sim()
        sim.add_vessel(VesselConfig("test", "scout"))
        assert any("test" in e and "scout" in e for e in sim.event_log)

    def test_post_task(self):
        sim = self._make_sim()
        t = Task("t1", "desc", [0x00], 1)
        sim.post_task(t)
        assert "t1" in sim.tasks
        assert sim.tasks["t1"].description == "desc"

    def test_post_task_broadcasts(self):
        sim = self._make_sim()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        sim.add_vessel(VesselConfig("v2", "vessel"))
        sim.post_task(Task("t1", "desc", [], 1))
        # Each vessel should get a task message
        assert len(sim.message_queue) == 2
        recipients = [m.recipient for m in sim.message_queue]
        assert "v1" in recipients
        assert "v2" in recipients

    def test_post_task_message_type(self):
        sim = self._make_sim()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        sim.post_task(Task("t1", "desc", [], 1))
        assert sim.message_queue[0].msg_type == MessageType.TASK
        assert sim.message_queue[0].payload["task_id"] == "t1"


# ── FleetSimulator Step/Run ──────────────────────────────────────────────

class TestFleetStepRun:
    def test_single_step_no_vessels(self):
        sim = FleetSimulator()
        active = sim.step()
        assert active is False

    def test_step_delivers_messages(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("a", "vessel"))
        sim.message_queue.append(Message("b", "a", MessageType.BEACON, {}))
        active = sim.step()
        assert active is True

    def test_step_message_to_unknown_recipient(self):
        """Messages to unknown vessels are dropped."""
        sim = FleetSimulator()
        sim.message_queue.append(Message("a", "nobody", MessageType.BEACON, {}))
        active = sim.step()
        assert active is False

    def test_beaon_logs(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("a", "vessel"))
        sim.message_queue.append(Message("b", "a", MessageType.BEACON, {}))
        sim.step()
        assert any("beacon" in e.lower() for e in sim.event_log)

    def test_tom_sawyer_task_claim(self):
        """Non-lighthouse vessels should volunteer for unassigned tasks."""
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("worker1", "vessel"))
        sim.post_task(Task("t1", "compute 42", [0x18, 0, 42, 0x00], 1))
        sim.run()
        assert sim.tasks["t1"].completed is True
        assert sim.tasks["t1"].assigned_to == "worker1"

    def test_lighthouse_does_not_claim_tasks(self):
        """Lighthouse vessels should not claim tasks (Tom Sawyer)."""
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("oracle1", "lighthouse"))
        sim.post_task(Task("t1", "compute 42", [0x18, 0, 42, 0x00], 1))
        sim.run()
        assert sim.tasks["t1"].completed is False

    def test_first_come_first_served(self):
        """Only one worker should claim a single task."""
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel"))
        sim.add_vessel(VesselConfig("w2", "vessel"))
        sim.post_task(Task("t1", "task", [0x18, 0, 1, 0x00], 1))
        sim.run()
        task = sim.tasks["t1"]
        assert task.completed is True
        # Exactly one worker should have it assigned
        assert task.assigned_to in ("w1", "w2")

    def test_multiple_tasks_distributed(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel", speed=2.0))
        sim.add_vessel(VesselConfig("w2", "vessel", speed=2.0))
        for i in range(4):
            sim.post_task(Task(f"t{i}", f"task {i}", [0x18, 0, i, 0x00], 1))
        result = sim.run(max_ticks=50)
        assert result["tasks_completed"] == 4

    def test_already_assigned_task_not_reclaimed(self):
        """An already-assigned task should not be claimed by another worker."""
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel"))
        sim.add_vessel(VesselConfig("w2", "vessel"))
        t = Task("t1", "task", [0x18, 0, 1, 0x00], 1, assigned_to="w1")
        sim.tasks["t1"] = t
        # Broadcast manually to avoid posting
        sim.message_queue.append(Message("coord", "w1", MessageType.TASK, {"task_id": "t1"}))
        sim.message_queue.append(Message("coord", "w2", MessageType.TASK, {"task_id": "t1"}))
        sim.run()
        assert t.assigned_to == "w1"

    def test_completed_task_not_reclaimed(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel"))
        sim.add_vessel(VesselConfig("w2", "vessel"))
        t = Task("t1", "task", [0x18, 0, 1, 0x00], 1, completed=True)
        sim.tasks["t1"] = t
        sim.message_queue.append(Message("coord", "w1", MessageType.TASK, {"task_id": "t1"}))
        sim.message_queue.append(Message("coord", "w2", MessageType.TASK, {"task_id": "t1"}))
        sim.run()
        assert t.assigned_to is None

    def test_task_result_stored(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel"))
        sim.post_task(Task("t1", "compute", [0x18, 0, 42, 0x00], 1))
        sim.run()
        assert sim.tasks["t1"].result is not None
        assert sim.tasks["t1"].result[0] == 42

    def test_worker_completed_tasks_tracked(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel", speed=2.0))
        for i in range(3):
            sim.post_task(Task(f"t{i}", f"task {i}", [0x18, 0, i, 0x00], 1))
        sim.run(max_ticks=30)
        assert len(sim.vessels["w1"].completed_tasks) == 3

    def test_run_returns_status(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        sim.post_task(Task("t1", "task", [0x00], 1))
        result = sim.run()
        assert "tick" in result
        assert "vessels" in result
        assert "tasks_total" in result
        assert "tasks_completed" in result

    def test_max_ticks(self):
        sim = FleetSimulator()
        # No vessels, no tasks — should stop immediately
        result = sim.run(max_ticks=5)
        assert result["tick"] <= 5

    def test_tick_increments(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        sim.message_queue.append(Message("x", "v1", MessageType.BEACON, {}))
        assert sim.tick == 0
        sim.step()
        assert sim.tick == 1
        sim.step()
        assert sim.tick == 2


# ── FleetSimulator Status ────────────────────────────────────────────────

class TestFleetStatus:
    def test_status_structure(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        status = sim.status()
        assert status["vessels"] == 1
        assert status["tasks_total"] == 0
        assert status["tasks_completed"] == 0
        assert "v1" in status["vessel_status"]

    def test_status_per_vessel(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        sim.add_vessel(VesselConfig("v2", "scout"))
        status = sim.status()
        vs = status["vessel_status"]
        for name in ("v1", "v2"):
            assert name in vs
            assert "state" in vs[name]
            assert "cycles" in vs[name]
            assert "completed_tasks" in vs[name]
            assert "mailbox" in vs[name]

    def test_status_vessel_state_value(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        status = sim.status()
        # State value should be a string (from enum .value)
        assert isinstance(status["vessel_status"]["v1"]["state"], str)

    def test_event_log_truncated(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        # Generate many events
        for i in range(50):
            sim.message_queue.append(
                Message(f"s{i}", "v1", MessageType.BEACON, {})
            )
        sim.run(max_ticks=60)
        status = sim.status()
        # Event log should be capped at 20
        assert len(status["event_log"]) <= 20


# ── FleetSimulator Event Log ─────────────────────────────────────────────

class TestEventLog:
    def test_add_vessel_logged(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("myv", "vessel"))
        assert any("myv" in e for e in sim.event_log)

    def test_post_task_logged(self):
        sim = FleetSimulator()
        sim.post_task(Task("t1", "my task", [], 1))
        assert any("t1" in e for e in sim.event_log)

    def test_task_completion_logged(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("w1", "vessel"))
        sim.post_task(Task("t1", "task", [0x18, 0, 1, 0x00], 1))
        sim.run()
        assert any("completed" in e.lower() for e in sim.event_log)

    def test_log_format(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        log_entry = sim.event_log[0]
        assert log_entry.startswith("[t0]")

    def test_tick_in_log(self):
        sim = FleetSimulator()
        sim.add_vessel(VesselConfig("v1", "vessel"))
        # add_vessel logs at tick 0
        sim.message_queue.append(Message("x", "v1", MessageType.BEACON, {}))
        sim.step()  # tick 1 — delivers beacon, logs at tick 1
        sim.message_queue.append(Message("y", "v1", MessageType.BEACON, {}))
        sim.step()  # tick 2 — delivers beacon, logs at tick 2
        ticks_in_log = {e.split("]")[0].strip("[t") for e in sim.event_log}
        assert "1" in ticks_in_log
        assert "2" in ticks_in_log
