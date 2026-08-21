"""B题问题3：使用班组1和班组2的设备完成A-E五个车间任务。

采用 OR-Tools CP-SAT 精确求解，同时决定：
1. 每道工序每类设备投入台数；
2. 具体设备编号及所属班组；
3. 同型设备均分工程量后的持续时间；
4. 每台设备的跨车间访问顺序与运输时间；
5. 各工序起止时刻和全部任务最短总工期。

程序会优先使用64位 Python 3.10+；若从常见的 Python 3.7 32位环境
启动，则自动切换到工作区自带的兼容解释器。
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
    """在32位或过旧解释器下自动切换到兼容的64位解释器。"""
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
            completed = subprocess.run(
                [str(executable), str(Path(__file__).resolve()), *sys.argv[1:]],
                cwd=str(ROOT),
            )
            raise SystemExit(completed.returncode)
    raise SystemExit("本程序要求 Python 3.10及以上的64位版本。")


ensure_compatible_python()
if SHARED_DEPS.exists():
    sys.path.insert(0, str(SHARED_DEPS))

try:
    from ortools.sat.python import cp_model
except (ImportError, OSError) as exc:
    raise SystemExit(
        "无法载入OR-Tools。请先运行问题2程序所用的依赖安装命令。\n"
        f"原始错误：{exc}"
    ) from exc


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
    def name(self) -> str:
        return f"{self.equipment_type}{self.team}-{self.index}"


COUNTS_PER_TEAM: Dict[str, int] = {
    "自动化输送臂": 4,
    "工业清洗机": 5,
    "精密灌装机": 5,
    "自动传感多功能机": 1,
    "高速抛光机": 1,
}

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
MOVING_SPEED = 2


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


def build_machines() -> Dict[str, List[Machine]]:
    return {
        equipment_type: [
            Machine(equipment_type, team, index)
            for team in (1, 2)
            for index in range(1, count + 1)
        ]
        for equipment_type, count in COUNTS_PER_TEAM.items()
    }


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


class ExactScheduler:
    def __init__(self, time_limit: float, workers: int, log_search: bool):
        self.operations, self.chains = build_operations()
        self.op_by_code = {op.code: op for op in self.operations}
        self.machines_by_type = build_machines()
        self.time_limit = time_limit
        self.workers = workers
        self.log_search = log_search
        self.model = cp_model.CpModel()
        self.horizon = 500_000
        self.op_start = {}
        self.op_end = {}
        self.req_end = {}
        self.req_duration = {}
        self.count_choice = {}
        self.assign = {}
        self.requirements_by_type: Dict[str, List[Tuple[str, int]]] = {
            k: [] for k in COUNTS_PER_TEAM
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
                req_end = self.model.NewIntVar(0, self.horizon, f"E_{op.code}_{ridx}")
                capacity = len(self.machines_by_type[requirement.equipment_type])
                durations = {
                    count: duration_seconds(op.workload, requirement.efficiency, count)
                    for count in range(1, capacity + 1)
                }
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

                assignment_vars = []
                for midx, _machine in enumerate(self.machines_by_type[requirement.equipment_type]):
                    x = self.model.NewBoolVar(f"X_{op.code}_{ridx}_{midx}")
                    self.assign[(key, midx)] = x
                    assignment_vars.append(x)
                self.model.Add(sum(assignment_vars) == sum(c * choices[c] for c in durations))

                self.req_end[key] = req_end
                self.req_duration[key] = duration
                self.count_choice[key] = choices
                requirement_ends.append(req_end)
            self.model.AddMaxEquality(end, requirement_ends)

        for chain in self.chains.values():
            for previous, current in zip(chain, chain[1:]):
                self.model.Add(self.op_start[current] >= self.op_end[previous])

        # 每台设备建立带虚拟仓库节点的Hamilton回路；弧上的时间约束包含运输时间。
        for equipment_type, requirement_keys in self.requirements_by_type.items():
            machines = self.machines_by_type[equipment_type]
            used_flags: Dict[Tuple[int, int], object] = {}
            for midx, machine in enumerate(machines):
                arcs = []
                empty = self.model.NewBoolVar(f"EMPTY_{equipment_type}_{midx}")
                used = self.model.NewBoolVar(f"USED_{equipment_type}_{midx}")
                self.model.Add(used + empty == 1)
                used_flags[(machine.team, machine.index)] = used
                arcs.append((0, 0, empty))

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
                    self.model.Add(
                        self.op_start[key_i[0]] >= initial_travel_time(machine.team, op_i.workshop)
                    ).OnlyEnforceIf(first)

                    for local_j, key_j in enumerate(requirement_keys, 1):
                        if local_i == local_j:
                            continue
                        arc = self.model.NewBoolVar(f"ARC_{equipment_type}_{midx}_{local_i}_{local_j}")
                        arcs.append((local_i, local_j, arc))
                        self.model.AddImplication(arc, x_i)
                        self.model.AddImplication(arc, self.assign[(key_j, midx)])
                        op_j = self.op_by_code[key_j[0]]
                        self.model.Add(
                            self.op_start[key_j[0]] >= self.req_end[key_i]
                            + travel_time(op_i.workshop, op_j.workshop)
                        ).OnlyEnforceIf(arc)
                self.model.AddCircuit(arcs)

            # 仅对同班组同型设备作对称性消除；不同班组初始位置不同，不能互换。
            for team in (1, 2):
                for index in range(1, COUNTS_PER_TEAM[equipment_type]):
                    self.model.Add(used_flags[(team, index)] >= used_flags[(team, index + 1)])

        final_codes = [self.chains[w][-1] for w in "ABCDE"]
        self.makespan = self.model.NewIntVar(0, self.horizon, "Cmax")
        self.model.AddMaxEquality(self.makespan, [self.op_end[c] for c in final_codes])
        self.model.Minimize(self.makespan)

    def solve(self):
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
                            "班组": f"班组{machine.team}", "班组编号": machine.team,
                            "车间": op.workshop, "工序编号": op.code,
                            "分配工程量": op.workload / count,
                            "开始秒": start, "结束秒": req_end,
                            "持续工作时间(s)": duration,
                        })

        by_machine: Dict[str, List[dict]] = {}
        for row in assignment_rows:
            by_machine.setdefault(row["设备编号"], []).append(row)
        for rows in by_machine.values():
            rows.sort(key=lambda r: (r["开始秒"], r["工序编号"]))
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


def validate_solution(scheduler: ExactScheduler, operation_rows, assignment_rows, makespan: int) -> None:
    op_result = {row["工序编号"]: row for row in operation_rows}
    for chain in scheduler.chains.values():
        for previous, current in zip(chain, chain[1:]):
            assert op_result[current]["开始秒"] >= op_result[previous]["结束秒"]

    for op in scheduler.operations:
        requirement_finishes = []
        for requirement in op.requirements:
            rows = [r for r in assignment_rows if r["工序编号"] == op.code
                    and r["设备类型"] == requirement.equipment_type]
            assert rows
            assert abs(sum(r["分配工程量"] for r in rows) - op.workload) < 1e-6
            expected = duration_seconds(op.workload, requirement.efficiency, len(rows))
            assert all(r["持续工作时间(s)"] == expected for r in rows)
            assert all(r["开始秒"] == op_result[op.code]["开始秒"] for r in rows)
            requirement_finishes.append(rows[0]["结束秒"])
        assert max(requirement_finishes) == op_result[op.code]["结束秒"]

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


def write_results(operation_rows, assignment_rows, makespan: int, status_text: str, bound: float):
    schedule_path = ROOT / "问题3_最优设备调度方案.csv"
    table3_path = ROOT / "表3_问题3结果.csv"
    operation_path = ROOT / "问题3_工序起止时间.csv"
    summary_path = ROOT / "问题3_求解摘要.txt"
    fields = ["序号", "设备编号", "设备类型", "班组", "车间", "工序编号",
              "分配工程量", "起始时间", "结束时间", "持续工作时间(s)",
              "运输起点", "运输时间(s)", "等待时间(s)"]
    with schedule_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(assignment_rows, 1):
            writer.writerow({
                "序号": index, "设备编号": row["设备编号"], "设备类型": row["设备类型"],
                "班组": row["班组"], "车间": row["车间"], "工序编号": row["工序编号"],
                "分配工程量": f'{row["分配工程量"]:.3f}',
                "起始时间": fmt_time(row["开始秒"]), "结束时间": fmt_time(row["结束秒"]),
                "持续工作时间(s)": row["持续工作时间(s)"],
                "运输起点": row["运输起点"], "运输时间(s)": row["运输时间(s)"],
                "等待时间(s)": row["等待时间(s)"],
            })
    # 直接对应题目表3列顺序的填报版本。
    with table3_path.open("w", encoding="utf-8-sig", newline="") as f:
        table3_fields = ["序号", "设备编号", "起始时间", "结束时间",
                         "持续工作时间(s)", "工序编号", "班组"]
        writer = csv.DictWriter(f, fieldnames=table3_fields)
        writer.writeheader()
        for index, row in enumerate(assignment_rows, 1):
            writer.writerow({"序号": index, "设备编号": row["设备编号"],
                             "起始时间": fmt_time(row["开始秒"]),
                             "结束时间": fmt_time(row["结束秒"]),
                             "持续工作时间(s)": row["持续工作时间(s)"],
                             "工序编号": row["工序编号"], "班组": row["班组"]})
    with operation_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields2 = ["车间", "工序编号", "工序开始", "工序结束", "工序持续时间(s)"]
        writer = csv.DictWriter(f, fieldnames=fields2)
        writer.writeheader()
        for row in operation_rows:
            writer.writerow({"车间": row["车间"], "工序编号": row["工序编号"],
                             "工序开始": fmt_time(row["开始秒"]),
                             "工序结束": fmt_time(row["结束秒"]),
                             "工序持续时间(s)": row["工序持续时间(s)"]})
    gap = max(0.0, (makespan - bound) / makespan) if makespan else 0.0
    summary = (f"求解状态：{status_text}\n当前最优完工时间：{makespan} s（{fmt_time(makespan)}）\n"
               f"严格下界：{bound:.0f} s（{fmt_time(int(math.ceil(bound)))}）\n"
               f"相对最优间隙：{gap:.6%}\n")
    summary_path.write_text(summary, encoding="utf-8")
    return schedule_path, table3_path, operation_path, summary_path, summary


def main() -> None:
    parser = argparse.ArgumentParser(description="B题问题3双班组精确CP-SAT优化")
    parser.add_argument("--time-limit", type=float, default=300.0,
                        help="证明最短总工期的最大求解时间（秒）")
    parser.add_argument("--refine-time", type=float, default=30.0,
                        help="固定最优总工期后紧凑化排程的最大求解时间（秒）")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--log-search", action="store_true")
    parser.add_argument("--no-refine", action="store_true")
    args = parser.parse_args()

    scheduler = ExactScheduler(args.time_limit, args.workers, args.log_search)
    scheduler.build()
    solver, status = scheduler.solve()
    primary_text = solver.StatusName(status)
    print(f"主目标求解状态：{primary_text}")
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit("未找到可行解，请增加 --time-limit 后重试。")
    makespan = solver.Value(scheduler.makespan)
    bound = solver.BestObjectiveBound()
    status_text = primary_text

    if status == cp_model.OPTIMAL and not args.no_refine:
        scheduler.model.Add(scheduler.makespan == makespan)
        scheduler.model.Minimize(sum(scheduler.op_end.values()))
        scheduler.time_limit = args.refine_time
        refined_solver, refined_status = scheduler.solve()
        if refined_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = refined_solver
            status_text = f"{primary_text}（最短总工期）；{solver.StatusName(refined_status)}（紧凑化）"
        bound = makespan

    operation_rows, assignment_rows = scheduler.extract(solver)
    validate_solution(scheduler, operation_rows, assignment_rows, makespan)
    paths = write_results(operation_rows, assignment_rows, makespan, status_text, bound)
    print("独立可行性校验：通过")
    print(paths[-1], end="")
    print("各车间最终完工时刻：")
    for workshop in "ABCDE":
        final = scheduler.chains[workshop][-1]
        end = next(r["结束秒"] for r in operation_rows if r["工序编号"] == final)
        print(f"{workshop}车间：{end} s（{fmt_time(end)}）")
    print("输出文件：")
    for path in paths[:-1]:
        print(path)


if __name__ == "__main__":
    main()
