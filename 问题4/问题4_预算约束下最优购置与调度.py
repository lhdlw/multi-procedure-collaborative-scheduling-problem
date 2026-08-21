"""B题问题4：50万元预算约束下的设备购置与双班组精确调度。

主目标：最小化五个车间全部任务的完工时间 Cmax；
次目标：在最优 Cmax 下最小化实际购置费用；
第三目标：固定前两层最优值后紧凑化非关键工序。

算法为 OR-Tools CP-SAT。模型同时决定购置设备类型及所属班组、每道工序
投入的同型设备数量、具体设备编号、设备跨车间路径和工序起止时刻。
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent
SHARED_DEPS = ROOT.parent / ".problem2_deps"


def ensure_compatible_python() -> None:
    """从32位/过旧 Python 启动时，自动切换到工作区的64位解释器。"""
    if sys.maxsize > 2**32 and sys.version_info >= (3, 10):
        return
    candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime"
        / "dependencies" / "python" / "python.exe",
        Path(r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    ]
    for executable in candidates:
        if executable.is_file() and executable.resolve() != Path(sys.executable).resolve():
            print(f"当前解释器不兼容，自动切换到：{executable}", flush=True)
            result = subprocess.run(
                [str(executable), str(Path(__file__).resolve()), *sys.argv[1:]],
                cwd=str(ROOT),
            )
            raise SystemExit(result.returncode)
    raise SystemExit("本程序要求 Python 3.10及以上的64位版本。")


ensure_compatible_python()
if SHARED_DEPS.exists():
    sys.path.insert(0, str(SHARED_DEPS))

try:
    from ortools.sat.python import cp_model
except (ImportError, OSError) as exc:
    raise SystemExit(f"无法载入OR-Tools：{exc}") from exc


@dataclass(frozen=True)
class Requirement:
    equipment_type: str
    efficiency: int


@dataclass(frozen=True)
class Operation:
    code: str
    workshop: str
    workload: int
    requirements: Tuple[Requirement, ...]


@dataclass(frozen=True)
class Machine:
    equipment_type: str
    team: int
    index: int

    @property
    def is_purchased(self) -> bool:
        return self.team == 0

    @property
    def name(self) -> str:
        if self.is_purchased:
            return f"{self.equipment_type}购-{self.index}"
        return f"{self.equipment_type}{self.team}-{self.index}"


EXISTING_PER_TEAM: Dict[str, int] = {
    "自动化输送臂": 4,
    "工业清洗机": 5,
    "精密灌装机": 5,
    "自动传感多功能机": 1,
    "高速抛光机": 1,
}

UNIT_PRICE: Dict[str, int] = {
    "自动化输送臂": 50_000,
    "工业清洗机": 40_000,
    "精密灌装机": 35_000,
    "自动传感多功能机": 80_000,
    "高速抛光机": 75_000,
}

BUDGET = 500_000
MOVING_SPEED = 2
INITIAL_DISTANCE = {
    1: {"A": 400, "B": 620, "C": 460, "D": 710, "E": 400},
    2: {"A": 500, "B": 460, "C": 620, "D": 680, "E": 550},
}
PAIR_DISTANCE = {
    ("A", "B"): 1020, ("A", "C"): 1050, ("A", "D"): 900,
    ("A", "E"): 1400, ("B", "C"): 1100, ("B", "D"): 1630,
    ("B", "E"): 720, ("C", "D"): 520, ("C", "E"): 850,
    ("D", "E"): 1030,
}


def req(name: str, efficiency: int) -> Requirement:
    return Requirement(name, efficiency)


def build_operations() -> Tuple[List[Operation], Dict[str, List[str]]]:
    operations: List[Operation] = []
    chains: Dict[str, List[str]] = {w: [] for w in "ABCDE"}

    def add(code: str, workshop: str, workload: int, requirements: Sequence[Requirement]):
        operations.append(Operation(code, workshop, workload, tuple(requirements)))
        chains[workshop].append(code)

    add("A1", "A", 300, [req("精密灌装机", 200), req("自动化输送臂", 250)])
    add("A2", "A", 500, [req("高速抛光机", 100), req("工业清洗机", 250)])
    add("A3", "A", 500, [req("自动传感多功能机", 100)])
    add("B1", "B", 120, [req("工业清洗机", 100)])
    add("B2", "B", 1500, [req("精密灌装机", 200), req("自动化输送臂", 300)])
    add("B3", "B", 360, [req("精密灌装机", 350)])
    add("B4", "B", 360, [req("高速抛光机", 120), req("自动传感多功能机", 100)])
    add("C1", "C", 720, [req("工业清洗机", 250), req("自动化输送臂", 250)])
    add("C2", "C", 720, [req("精密灌装机", 350)])
    for cycle in range(1, 4):
        add(f"C3-{cycle}", "C", 360, [req("精密灌装机", 200), req("自动化输送臂", 250)])
        add(f"C4-{cycle}", "C", 400, [req("高速抛光机", 120), req("工业清洗机", 100)])
        add(f"C5-{cycle}", "C", 400, [req("自动传感多功能机", 100)])
    add("D1", "D", 600, [req("工业清洗机", 250)])
    add("D2", "D", 800, [req("精密灌装机", 200), req("自动化输送臂", 300)])
    add("D3", "D", 450, [req("精密灌装机", 350)])
    add("D4", "D", 1500, [req("高速抛光机", 120), req("自动传感多功能机", 300)])
    add("D5", "D", 1500, [req("自动传感多功能机", 300)])
    add("D6", "D", 700, [req("高速抛光机", 100)])
    add("E1", "E", 1000, [req("工业清洗机", 250)])
    add("E2", "E", 600, [req("精密灌装机", 350)])
    add("E3", "E", 600, [req("自动传感多功能机", 300), req("工业清洗机", 100)])
    return operations, chains


def build_candidate_machines(fixed_totals=None) -> Dict[str, List[Machine]]:
    """新购设备先不定班组；其首任务确定后再归入初始运输更短的班组。"""
    result: Dict[str, List[Machine]] = {}
    for equipment_type, current in EXISTING_PER_TEAM.items():
        existing = [
            Machine(equipment_type, team, index)
            for team in (1, 2)
            for index in range(1, current + 1)
        ]
        extra_slots = (BUDGET // UNIT_PRICE[equipment_type]
                       if fixed_totals is None else fixed_totals.get(equipment_type, 0))
        purchased = [
            Machine(equipment_type, 0, index)
            for index in range(1, extra_slots + 1)
        ]
        result[equipment_type] = existing + purchased
    return result


def travel_time(origin: str, destination: str) -> int:
    if origin == destination:
        return 0
    return math.ceil(PAIR_DISTANCE[tuple(sorted((origin, destination)))] / MOVING_SPEED)


def initial_travel_time(team: int, workshop: str) -> int:
    return math.ceil(INITIAL_DISTANCE[team][workshop] / MOVING_SPEED)


def duration_seconds(workload: int, efficiency: int, machine_count: int) -> int:
    return math.ceil(workload * 3600 / (efficiency * machine_count))


def fmt_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


class BudgetScheduler:
    def __init__(self, time_limit: float, workers: int, log_search: bool,
                 fixed_totals=None):
        self.operations, self.chains = build_operations()
        self.op_by_code = {op.code: op for op in self.operations}
        self.fixed_totals = fixed_totals
        self.machines_by_type = build_candidate_machines(fixed_totals)
        self.time_limit = time_limit
        self.workers = workers
        self.log_search = log_search
        self.model = cp_model.CpModel()
        self.horizon = 300_000
        self.op_start = {}
        self.op_end = {}
        self.req_end = {}
        self.req_duration = {}
        self.count_choice = {}
        self.assign = {}
        self.used = {}
        self.requirements_by_type: Dict[str, List[Tuple[str, int]]] = {
            k: [] for k in EXISTING_PER_TEAM
        }

    def build(self) -> None:
        for op in self.operations:
            start = self.model.NewIntVar(0, self.horizon, f"S_{op.code}")
            end = self.model.NewIntVar(0, self.horizon, f"C_{op.code}")
            self.op_start[op.code] = start
            self.op_end[op.code] = end
            requirement_ends = []

            for ridx, requirement in enumerate(op.requirements):
                key = (op.code, ridx)
                self.requirements_by_type[requirement.equipment_type].append(key)
                machines = self.machines_by_type[requirement.equipment_type]
                capacity = len(machines)
                durations = {
                    count: duration_seconds(op.workload, requirement.efficiency, count)
                    for count in range(1, capacity + 1)
                }
                req_end = self.model.NewIntVar(0, self.horizon, f"E_{op.code}_{ridx}")
                duration = self.model.NewIntVar(
                    min(durations.values()), max(durations.values()), f"P_{op.code}_{ridx}"
                )
                choices = {
                    count: self.model.NewBoolVar(f"Y_{op.code}_{ridx}_{count}")
                    for count in durations
                }
                self.model.AddExactlyOne(choices.values())
                self.model.Add(duration == sum(durations[c] * choices[c] for c in durations))
                self.model.Add(req_end == start + duration)

                assignments = []
                for midx, _machine in enumerate(machines):
                    x = self.model.NewBoolVar(f"X_{op.code}_{ridx}_{midx}")
                    self.assign[(key, midx)] = x
                    assignments.append(x)
                self.model.Add(sum(assignments) == sum(c * choices[c] for c in durations))

                self.req_end[key] = req_end
                self.req_duration[key] = duration
                self.count_choice[key] = choices
                requirement_ends.append(req_end)
            self.model.AddMaxEquality(end, requirement_ends)

        for chain in self.chains.values():
            for previous, current in zip(chain, chain[1:]):
                self.model.Add(self.op_start[current] >= self.op_end[previous])

        purchase_terms = []
        for equipment_type, requirement_keys in self.requirements_by_type.items():
            machines = self.machines_by_type[equipment_type]
            used_by_team_index = {}
            for midx, machine in enumerate(machines):
                arcs = []
                empty = self.model.NewBoolVar(f"EMPTY_{equipment_type}_{midx}")
                used = self.model.NewBoolVar(f"USED_{equipment_type}_{midx}")
                self.used[(equipment_type, midx)] = used
                used_by_team_index[(machine.team, machine.index)] = used
                self.model.Add(used + empty == 1)
                arcs.append((0, 0, empty))
                if machine.is_purchased:
                    purchase_terms.append(UNIT_PRICE[equipment_type] * used)
                    if self.fixed_totals is not None:
                        self.model.Add(used == 1)

                for local_i, key_i in enumerate(requirement_keys, 1):
                    x_i = self.assign[(key_i, midx)]
                    arcs.append((local_i, local_i, x_i.Not()))
                    first = self.model.NewBoolVar(f"FIRST_{equipment_type}_{midx}_{local_i}")
                    last = self.model.NewBoolVar(f"LAST_{equipment_type}_{midx}_{local_i}")
                    arcs.append((0, local_i, first))
                    arcs.append((local_i, 0, last))
                    self.model.AddImplication(first, x_i)
                    self.model.AddImplication(last, x_i)
                    op_i = self.op_by_code[key_i[0]]
                    first_travel = (
                        min(initial_travel_time(team, op_i.workshop) for team in (1, 2))
                        if machine.is_purchased
                        else initial_travel_time(machine.team, op_i.workshop)
                    )
                    self.model.Add(
                        self.op_start[key_i[0]] >= first_travel
                    ).OnlyEnforceIf(first)

                    for local_j, key_j in enumerate(requirement_keys, 1):
                        if local_i == local_j:
                            continue
                        arc = self.model.NewBoolVar(
                            f"ARC_{equipment_type}_{midx}_{local_i}_{local_j}"
                        )
                        arcs.append((local_i, local_j, arc))
                        self.model.AddImplication(arc, x_i)
                        self.model.AddImplication(arc, self.assign[(key_j, midx)])
                        op_j = self.op_by_code[key_j[0]]
                        self.model.Add(
                            self.op_start[key_j[0]] >= self.req_end[key_i]
                            + travel_time(op_i.workshop, op_j.workshop)
                        ).OnlyEnforceIf(arc)
                self.model.AddCircuit(arcs)

            # 同班组同类型设备等价：低编号设备优先使用，显著消除对称解。
            for team in (0, 1, 2):
                if not any(m.team == team for m in machines):
                    continue
                maximum_index = max(
                    m.index for m in machines if m.team == team
                )
                for index in range(1, maximum_index):
                    self.model.Add(
                        used_by_team_index[(team, index)]
                        >= used_by_team_index[(team, index + 1)]
                    )

        self.purchase_cost = self.model.NewIntVar(0, BUDGET, "PurchaseCost")
        if self.fixed_totals is None:
            self.model.Add(self.purchase_cost == sum(purchase_terms))
        else:
            fixed_cost = sum(
                UNIT_PRICE[t] * self.fixed_totals.get(t, 0)
                for t in EXISTING_PER_TEAM
            )
            self.model.Add(self.purchase_cost == fixed_cost)
        self.model.Add(self.purchase_cost <= BUDGET)

        # 显式加入各类设备的总负荷下界，强化分支定界。
        self.purchase_count_by_type = {}
        self.load_lower_bound_by_type = {}
        for equipment_type, machines in self.machines_by_type.items():
            purchased_flags = [
                self.used[(equipment_type, midx)]
                for midx, machine in enumerate(machines) if machine.is_purchased
            ]
            count_var = self.model.NewIntVar(0, len(purchased_flags),
                                             f"BoughtCount_{equipment_type}")
            self.model.Add(count_var == sum(purchased_flags))
            self.purchase_count_by_type[equipment_type] = count_var
            total_nominal_work = sum(
                op.workload * 3600 / requirement.efficiency
                for op in self.operations for requirement in op.requirements
                if requirement.equipment_type == equipment_type
            )
            base = 2 * EXISTING_PER_TEAM[equipment_type]
            bounds = [
                math.ceil(total_nominal_work / (base + extra))
                for extra in range(len(purchased_flags) + 1)
            ]
            lb_var = self.model.NewIntVar(min(bounds), max(bounds),
                                          f"LoadLB_{equipment_type}")
            self.model.AddElement(count_var, bounds, lb_var)
            self.load_lower_bound_by_type[equipment_type] = lb_var

        final_codes = [self.chains[w][-1] for w in "ABCDE"]
        self.makespan = self.model.NewIntVar(0, self.horizon, "Cmax")
        self.model.AddMaxEquality(self.makespan, [self.op_end[c] for c in final_codes])
        for lb_var in self.load_lower_bound_by_type.values():
            self.model.Add(self.makespan >= lb_var)
        self.model.Minimize(self.makespan)

    def solve(self, objective: str):
        if objective == "makespan":
            self.model.Minimize(self.makespan)
        elif objective == "cost":
            self.model.Minimize(self.purchase_cost)
        elif objective == "compact":
            self.model.Minimize(sum(self.op_end.values()))
        else:
            raise ValueError(objective)
        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = self.time_limit
        solver.parameters.num_search_workers = self.workers
        solver.parameters.random_seed = 20260820
        solver.parameters.log_search_progress = self.log_search
        solver.parameters.cp_model_presolve = True
        solver.parameters.linearization_level = 2
        status = solver.Solve(self.model)
        return solver, status

    def selected_count(self, solver, key) -> int:
        return next(c for c, flag in self.count_choice[key].items() if solver.Value(flag))

    def purchased_counts(self, assignment_rows) -> Dict[Tuple[str, int], int]:
        counts = {(t, team): 0 for t in EXISTING_PER_TEAM for team in (1, 2)}
        seen = set()
        for row in assignment_rows:
            if row["设备来源"] == "购置" and row["设备编号"] not in seen:
                seen.add(row["设备编号"])
                counts[(row["设备类型"], row["班组编号"])] += 1
        return counts

    def extract(self, solver):
        operation_rows, assignment_rows = [], []
        for op in self.operations:
            start = solver.Value(self.op_start[op.code])
            end = solver.Value(self.op_end[op.code])
            operation_rows.append({
                "车间": op.workshop, "工序编号": op.code,
                "开始秒": start, "结束秒": end, "工序持续时间(s)": end - start,
            })
            for ridx, requirement in enumerate(op.requirements):
                key = (op.code, ridx)
                count = self.selected_count(solver, key)
                duration = solver.Value(self.req_duration[key])
                req_end = solver.Value(self.req_end[key])
                for midx, machine in enumerate(self.machines_by_type[requirement.equipment_type]):
                    if solver.Value(self.assign[(key, midx)]):
                        assignment_rows.append({
                            "设备编号": machine.name, "设备类型": machine.equipment_type,
                            "设备来源": "购置" if machine.is_purchased else "原有",
                            "班组": f"班组{machine.team}", "班组编号": machine.team,
                            "车间": op.workshop, "工序编号": op.code,
                            "分配工程量": op.workload / count,
                            "开始秒": start, "结束秒": req_end,
                            "持续工作时间(s)": duration,
                        })

        by_machine: Dict[str, List[dict]] = {}
        for row in assignment_rows:
            by_machine.setdefault(row["设备编号"], []).append(row)
        purchase_sequence = {(t, team): 0 for t in EXISTING_PER_TEAM for team in (1, 2)}
        for rows in by_machine.values():
            rows.sort(key=lambda r: (r["开始秒"], r["工序编号"]))
            if rows[0]["设备来源"] == "购置":
                first_workshop = rows[0]["车间"]
                team = min(
                    (1, 2),
                    key=lambda g: (initial_travel_time(g, first_workshop), g),
                )
                equipment_type = rows[0]["设备类型"]
                purchase_sequence[(equipment_type, team)] += 1
                new_index = (EXISTING_PER_TEAM[equipment_type]
                             + purchase_sequence[(equipment_type, team)])
                new_name = f"{equipment_type}{team}-{new_index}"
                for row in rows:
                    row["班组编号"] = team
                    row["班组"] = f"班组{team}"
                    row["设备编号"] = new_name
            previous_workshop, previous_end = None, 0
            for row in rows:
                if previous_workshop is None:
                    travel = initial_travel_time(row["班组编号"], row["车间"])
                    origin = row["班组"]
                else:
                    travel = travel_time(previous_workshop, row["车间"])
                    origin = previous_workshop
                row["运输起点"] = origin
                row["运输时间(s)"] = travel
                row["等待时间(s)"] = row["开始秒"] - previous_end - travel
                previous_workshop, previous_end = row["车间"], row["结束秒"]
        assignment_rows.sort(key=lambda r: (r["开始秒"], r["设备编号"], r["工序编号"]))
        return operation_rows, assignment_rows


def validate_solution(scheduler, operation_rows, assignment_rows, purchase_counts,
                      purchase_cost: int, makespan: int) -> None:
    assert purchase_cost <= BUDGET
    expected_cost = sum(
        UNIT_PRICE[equipment_type] * count
        for (equipment_type, _team), count in purchase_counts.items()
    )
    assert expected_cost == purchase_cost

    op_result = {row["工序编号"]: row for row in operation_rows}
    for chain in scheduler.chains.values():
        for previous, current in zip(chain, chain[1:]):
            assert op_result[current]["开始秒"] >= op_result[previous]["结束秒"]

    for op in scheduler.operations:
        for requirement in op.requirements:
            rows = [r for r in assignment_rows if r["工序编号"] == op.code
                    and r["设备类型"] == requirement.equipment_type]
            assert rows
            assert abs(sum(r["分配工程量"] for r in rows) - op.workload) < 1e-6
            expected = duration_seconds(op.workload, requirement.efficiency, len(rows))
            assert all(r["持续工作时间(s)"] == expected for r in rows)
            assert all(r["开始秒"] == op_result[op.code]["开始秒"] for r in rows)
        finishes = [r["结束秒"] for r in assignment_rows if r["工序编号"] == op.code]
        assert max(finishes) == op_result[op.code]["结束秒"]

    by_machine: Dict[str, List[dict]] = {}
    for row in assignment_rows:
        by_machine.setdefault(row["设备编号"], []).append(row)
    for rows in by_machine.values():
        rows.sort(key=lambda r: (r["开始秒"], r["工序编号"]))
        previous_end, previous_workshop = 0, None
        for row in rows:
            required = (initial_travel_time(row["班组编号"], row["车间"])
                        if previous_workshop is None
                        else travel_time(previous_workshop, row["车间"]))
            assert row["开始秒"] >= previous_end + required
            previous_end, previous_workshop = row["结束秒"], row["车间"]

    assert max(op_result[scheduler.chains[w][-1]]["结束秒"] for w in "ABCDE") == makespan


def write_results(scheduler, operation_rows, assignment_rows, purchase_counts,
                  makespan, purchase_cost, status_lines):
    table4_path = ROOT / "表4_问题4结果.csv"
    detailed_path = ROOT / "问题4_最优设备调度方案.csv"
    table5_path = ROOT / "表5_问题4设备购买情况.csv"
    operation_path = ROOT / "问题4_工序起止时间.csv"
    summary_path = ROOT / "问题4_求解摘要.txt"

    with table4_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["序号", "设备编号", "起始时间", "结束时间",
                  "持续工作时间(s)", "工序编号", "班组"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(assignment_rows, 1):
            writer.writerow({
                "序号": index, "设备编号": row["设备编号"],
                "起始时间": fmt_time(row["开始秒"]), "结束时间": fmt_time(row["结束秒"]),
                "持续工作时间(s)": row["持续工作时间(s)"],
                "工序编号": row["工序编号"], "班组": row["班组"],
            })

    with detailed_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["序号", "设备编号", "设备类型", "设备来源", "班组", "车间", "工序编号",
                  "分配工程量", "起始时间", "结束时间", "持续工作时间(s)",
                  "运输起点", "运输时间(s)", "等待时间(s)"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(assignment_rows, 1):
            writer.writerow({
                "序号": index, "设备编号": row["设备编号"], "设备类型": row["设备类型"],
                "设备来源": row["设备来源"], "班组": row["班组"], "车间": row["车间"],
                "工序编号": row["工序编号"], "分配工程量": f'{row["分配工程量"]:.3f}',
                "起始时间": fmt_time(row["开始秒"]), "结束时间": fmt_time(row["结束秒"]),
                "持续工作时间(s)": row["持续工作时间(s)"],
                "运输起点": row["运输起点"], "运输时间(s)": row["运输时间(s)"],
                "等待时间(s)": row["等待时间(s)"],
            })

    with table5_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["设备名称", "班组1购买台数", "班组2购买台数", "单价(元/台)", "小计(元)"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for equipment_type in EXISTING_PER_TEAM:
            team1 = purchase_counts[(equipment_type, 1)]
            team2 = purchase_counts[(equipment_type, 2)]
            writer.writerow({
                "设备名称": equipment_type, "班组1购买台数": team1,
                "班组2购买台数": team2, "单价(元/台)": UNIT_PRICE[equipment_type],
                "小计(元)": (team1 + team2) * UNIT_PRICE[equipment_type],
            })
        writer.writerow({"设备名称": "合计", "小计(元)": purchase_cost})

    with operation_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["车间", "工序编号", "工序开始", "工序结束", "工序持续时间(s)"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in operation_rows:
            writer.writerow({
                "车间": row["车间"], "工序编号": row["工序编号"],
                "工序开始": fmt_time(row["开始秒"]), "工序结束": fmt_time(row["结束秒"]),
                "工序持续时间(s)": row["工序持续时间(s)"],
            })

    lines = list(status_lines)
    lines += [
        f"最优总工期：{makespan} s（{fmt_time(makespan)}）",
        f"最优总工期下的最少购置费用：{purchase_cost} 元",
        f"预算余额：{BUDGET - purchase_cost} 元",
        "独立可行性校验：通过",
        "购置方案：",
    ]
    for equipment_type in EXISTING_PER_TEAM:
        lines.append(
            f"  {equipment_type}：班组1 {purchase_counts[(equipment_type, 1)]} 台，"
            f"班组2 {purchase_counts[(equipment_type, 2)]} 台"
        )
    lines.append("各车间最终完工时刻：")
    for workshop in "ABCDE":
        final_code = scheduler.chains[workshop][-1]
        end = next(r["结束秒"] for r in operation_rows if r["工序编号"] == final_code)
        lines.append(f"  {workshop}车间：{end} s（{fmt_time(end)}）")
    summary = "\n".join(lines) + "\n"
    summary_path.write_text(summary, encoding="utf-8")
    return [table4_path, detailed_path, table5_path, operation_path, summary_path], summary


def main() -> None:
    parser = argparse.ArgumentParser(description="B题问题4预算约束下精确购置—调度联合优化")
    parser.add_argument("--time-limit", type=float, default=600.0,
                        help="主目标全局最优证明的最大求解时间（秒）")
    parser.add_argument("--cost-time", type=float, default=300.0,
                        help="固定最优总工期后最小购置费用的求解时间（秒）")
    parser.add_argument("--refine-time", type=float, default=60.0,
                        help="固定前两层最优值后紧凑化排程的求解时间（秒）")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--log-search", action="store_true")
    args = parser.parse_args()

    scheduler = BudgetScheduler(args.time_limit, args.workers, args.log_search)
    scheduler.build()

    solver, status = scheduler.solve("makespan")
    status_name = solver.StatusName(status)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit("未找到可行解，请增加 --time-limit 后重试。")
    makespan = solver.Value(scheduler.makespan)
    bound = solver.BestObjectiveBound()
    status_lines = [
        f"第一层（最短总工期）状态：{status_name}",
        f"第一层可行解上界：{makespan} s（{fmt_time(makespan)}）",
        f"第一层严格下界：{math.ceil(bound)} s（{fmt_time(math.ceil(bound))}）",
    ]
    if status != cp_model.OPTIMAL:
        status_lines.append(
            f"第一层相对最优间隙：{max(0.0, (makespan-bound)/makespan):.6%}"
        )
        print("\n".join(status_lines))
        raise SystemExit("主目标尚未证明全局最优；请增加 --time-limit 后重试。")

    scheduler.model.Add(scheduler.makespan == makespan)
    scheduler.time_limit = args.cost_time
    cost_solver, cost_status = scheduler.solve("cost")
    if cost_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit("固定最优总工期后未找到购置方案。")
    solver = cost_solver
    purchase_cost = solver.Value(scheduler.purchase_cost)
    cost_bound = solver.BestObjectiveBound()
    status_lines += [
        f"第二层（最少购置费用）状态：{solver.StatusName(cost_status)}",
        f"第二层购置费用：{purchase_cost} 元；严格下界：{math.ceil(cost_bound)} 元",
    ]
    if cost_status == cp_model.OPTIMAL:
        scheduler.model.Add(scheduler.purchase_cost == purchase_cost)
        scheduler.time_limit = args.refine_time
        compact_solver, compact_status = scheduler.solve("compact")
        if compact_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = compact_solver
            status_lines.append(f"第三层（排程紧凑化）状态：{solver.StatusName(compact_status)}")

    operation_rows, assignment_rows = scheduler.extract(solver)
    purchase_counts = scheduler.purchased_counts(assignment_rows)
    validate_solution(
        scheduler, operation_rows, assignment_rows, purchase_counts,
        purchase_cost, makespan,
    )
    paths, summary = write_results(
        scheduler, operation_rows, assignment_rows, purchase_counts,
        makespan, purchase_cost, status_lines,
    )
    print(summary, end="")
    print("输出文件：")
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
