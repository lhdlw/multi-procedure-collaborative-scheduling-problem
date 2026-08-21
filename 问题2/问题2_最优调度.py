"""B题问题2：仅使用班组1设备完成A-E五个车间的精确优化模型。

算法：OR-Tools CP-SAT（约束规划/分支定界），而非遗传算法等近似方法。
模型同时决定：
1. 每道工序每类设备的投入台数；
2. 具体设备编号；
3. 同型多机均分后的作业时长；
4. 每台设备跨车间的访问顺序与运输时间；
5. 所有工序的起止时间及总完工时间。

运行前需要将 OR-Tools 安装在当前目录的 .problem2_deps 中：
python -m pip install ortools --target .problem2_deps
"""

from __future__ import annotations

import argparse
import csv
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


ROOT = Path(__file__).resolve().parent
DEPS = ROOT / ".problem2_deps"


def ensure_compatible_python() -> None:
    """自动处理用户误用Python 3.7 32位运行64位OR-Tools的情况。"""
    is_64_bit = sys.maxsize > 2**32
    is_supported_version = sys.version_info >= (3, 10)
    if is_64_bit and is_supported_version:
        return
    candidates = [
        Path.home()
        / ".cache"
        / "codex-runtimes"
        / "codex-primary-runtime"
        / "dependencies"
        / "python"
        / "python.exe",
        Path(r"C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"),
    ]
    for executable in candidates:
        if executable.is_file() and executable.resolve() != Path(sys.executable).resolve():
            print(
                f"检测到当前解释器为 Python {sys.version_info.major}.{sys.version_info.minor} "
                f"({'64位' if is_64_bit else '32位'})，与OR-Tools不兼容。",
                flush=True,
            )
            print(f"正在自动切换到兼容解释器：{executable}", flush=True)
            command = [str(executable), str(Path(__file__).resolve()), *sys.argv[1:]]
            completed = subprocess.run(command, cwd=str(ROOT))
            raise SystemExit(completed.returncode)

    raise SystemExit(
        "当前使用的是不兼容的Python解释器。\n"
        "本程序要求Python 3.10及以上的64位版本。\n"
        "请安装Python 3.12 64位，并在VS Code中执行“Python: Select Interpreter”"
        "选择64位解释器后重新运行。"
    )


ensure_compatible_python()

if DEPS.exists():
    sys.path.insert(0, str(DEPS))

try:
    from ortools.sat.python import cp_model
except (ImportError, OSError) as exc:
    raise SystemExit(
        "无法载入OR-Tools。请确认使用Python 3.10及以上的64位版本，并执行：\n"
        "python -m pip install ortools --target .problem2_deps\n"
        f"原始错误：{exc}"
    ) from exc


@dataclass(frozen=True)
class Requirement:
    equipment_type: str
    efficiency: int  # m^3/h


@dataclass(frozen=True)
class Operation:
    code: str
    workshop: str
    workload: int
    requirements: Tuple[Requirement, ...]


EQUIPMENT_COUNTS: Dict[str, int] = {
    "自动化输送臂": 4,
    "工业清洗机": 5,
    "精密灌装机": 5,
    "自动传感多功能机": 1,
    "高速抛光机": 1,
}

EQUIPMENT_PREFIX = {
    "自动化输送臂": "自动化输送臂1-",
    "工业清洗机": "工业清洗机1-",
    "精密灌装机": "精密灌装机1-",
    "自动传感多功能机": "自动传感多功能机1-",
    "高速抛光机": "高速抛光机1-",
}

INITIAL_DISTANCE = {"A": 400, "B": 620, "C": 460, "D": 710, "E": 400}

PAIR_DISTANCE = {
    ("A", "B"): 1020,
    ("A", "C"): 1050,
    ("A", "D"): 900,
    ("A", "E"): 1400,
    ("B", "C"): 1100,
    ("B", "D"): 1630,
    ("B", "E"): 720,
    ("C", "D"): 520,
    ("C", "E"): 850,
    ("D", "E"): 1030,
}

MOVING_SPEED = 2  # m/s


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


def travel_time(origin: str, destination: str) -> int:
    if origin == destination:
        return 0
    key = tuple(sorted((origin, destination)))
    return math.ceil(PAIR_DISTANCE[key] / MOVING_SPEED)


def initial_travel_time(workshop: str) -> int:
    return math.ceil(INITIAL_DISTANCE[workshop] / MOVING_SPEED)


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
        self.time_limit = time_limit
        self.workers = workers
        self.log_search = log_search
        self.model = cp_model.CpModel()
        self.horizon = 500_000

        self.op_start = {}
        self.op_end = {}
        self.req_start = {}
        self.req_end = {}
        self.req_duration = {}
        self.count_choice = {}
        self.assign = {}
        self.requirements_by_type: Dict[str, List[Tuple[str, int]]] = {
            k: [] for k in EQUIPMENT_COUNTS
        }

    def build(self):
        # Operation and requirement variables.
        for op in self.operations:
            s = self.model.NewIntVar(0, self.horizon, f"S_{op.code}")
            c = self.model.NewIntVar(0, self.horizon, f"C_{op.code}")
            self.op_start[op.code] = s
            self.op_end[op.code] = c
            req_ends = []

            for ridx, requirement in enumerate(op.requirements):
                key = (op.code, ridx)
                self.requirements_by_type[requirement.equipment_type].append(key)
                rs = s  # 两类设备同时开始
                re = self.model.NewIntVar(0, self.horizon, f"E_{op.code}_{ridx}")
                machine_cap = EQUIPMENT_COUNTS[requirement.equipment_type]
                durations = {
                    m: duration_seconds(op.workload, requirement.efficiency, m)
                    for m in range(1, machine_cap + 1)
                }
                d = self.model.NewIntVar(
                    min(durations.values()), max(durations.values()), f"P_{op.code}_{ridx}"
                )
                choices = {
                    m: self.model.NewBoolVar(f"Y_{op.code}_{ridx}_{m}")
                    for m in durations
                }
                self.model.AddExactlyOne(choices.values())
                self.model.Add(d == sum(durations[m] * choices[m] for m in durations))
                self.model.Add(re == rs + d)

                assignment_vars = []
                for machine in range(1, machine_cap + 1):
                    x = self.model.NewBoolVar(f"X_{op.code}_{ridx}_{machine}")
                    self.assign[(key, machine)] = x
                    assignment_vars.append(x)
                self.model.Add(
                    sum(assignment_vars)
                    == sum(m * choices[m] for m in durations)
                )

                self.req_start[key] = rs
                self.req_end[key] = re
                self.req_duration[key] = d
                self.count_choice[key] = choices
                req_ends.append(re)

            self.model.AddMaxEquality(c, req_ends)

        # Fixed operation chains inside each workshop.
        for workshop, chain in self.chains.items():
            for previous, current in zip(chain, chain[1:]):
                self.model.Add(self.op_start[current] >= self.op_end[previous])

        # Individual-machine routes with sequence-dependent inter-workshop travel.
        used_by_type: Dict[str, List[cp_model.IntVar]] = {}
        for equipment_type, requirement_keys in self.requirements_by_type.items():
            used_by_type[equipment_type] = []
            machine_cap = EQUIPMENT_COUNTS[equipment_type]
            for machine in range(1, machine_cap + 1):
                arcs = []
                empty = self.model.NewBoolVar(f"EMPTY_{equipment_type}_{machine}")
                used = self.model.NewBoolVar(f"USED_{equipment_type}_{machine}")
                self.model.Add(used + empty == 1)
                used_by_type[equipment_type].append(used)
                arcs.append((0, 0, empty))

                for local_i, key_i in enumerate(requirement_keys, 1):
                    x_i = self.assign[(key_i, machine)]
                    arcs.append((local_i, local_i, x_i.Not()))

                    first = self.model.NewBoolVar(
                        f"ARC0_{equipment_type}_{machine}_{local_i}"
                    )
                    last = self.model.NewBoolVar(
                        f"ARCEND_{equipment_type}_{machine}_{local_i}"
                    )
                    arcs.append((0, local_i, first))
                    arcs.append((local_i, 0, last))
                    self.model.AddImplication(first, x_i)
                    self.model.AddImplication(last, x_i)
                    op_i = self.op_by_code[key_i[0]]
                    self.model.Add(
                        self.req_start[key_i] >= initial_travel_time(op_i.workshop)
                    ).OnlyEnforceIf(first)

                    for local_j, key_j in enumerate(requirement_keys, 1):
                        if local_i == local_j:
                            continue
                        arc = self.model.NewBoolVar(
                            f"ARC_{equipment_type}_{machine}_{local_i}_{local_j}"
                        )
                        arcs.append((local_i, local_j, arc))
                        self.model.AddImplication(arc, x_i)
                        self.model.AddImplication(arc, self.assign[(key_j, machine)])
                        op_j = self.op_by_code[key_j[0]]
                        transition = travel_time(op_i.workshop, op_j.workshop)
                        self.model.Add(
                            self.req_start[key_j]
                            >= self.req_end[key_i] + transition
                        ).OnlyEnforceIf(arc)

                self.model.AddCircuit(arcs)

            # Idle-machine symmetry breaking: lower-index machines are used first.
            for first, second in zip(
                used_by_type[equipment_type], used_by_type[equipment_type][1:]
            ):
                self.model.Add(first >= second)

        # Makespan equals the latest workshop completion time.
        final_operations = [self.chains[w][-1] for w in "ABCDE"]
        self.makespan = self.model.NewIntVar(0, self.horizon, "Cmax")
        self.model.AddMaxEquality(
            self.makespan, [self.op_end[code] for code in final_operations]
        )
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

    def selected_machine_count(self, solver, key):
        for count, literal in self.count_choice[key].items():
            if solver.Value(literal):
                return count
        raise RuntimeError("没有选中的设备数量")

    def extract(self, solver):
        operation_rows = []
        assignment_rows = []

        for op in self.operations:
            op_start = solver.Value(self.op_start[op.code])
            op_end = solver.Value(self.op_end[op.code])
            operation_rows.append(
                {
                    "车间": op.workshop,
                    "工序编号": op.code,
                    "工序开始": op_start,
                    "工序结束": op_end,
                    "工序持续时间": op_end - op_start,
                }
            )
            for ridx, requirement in enumerate(op.requirements):
                key = (op.code, ridx)
                count = self.selected_machine_count(solver, key)
                workload_each = op.workload / count
                start = solver.Value(self.req_start[key])
                end = solver.Value(self.req_end[key])
                duration = solver.Value(self.req_duration[key])
                for machine in range(1, EQUIPMENT_COUNTS[requirement.equipment_type] + 1):
                    if solver.Value(self.assign[(key, machine)]):
                        assignment_rows.append(
                            {
                                "设备类型": requirement.equipment_type,
                                "设备编号": EQUIPMENT_PREFIX[requirement.equipment_type] + str(machine),
                                "车间": op.workshop,
                                "工序编号": op.code,
                                "分配工程量": workload_each,
                                "开始秒": start,
                                "结束秒": end,
                                "持续工作时间(s)": duration,
                            }
                        )

        # Recover each machine's actual travel before every assigned task.
        by_machine: Dict[str, List[dict]] = {}
        for row in assignment_rows:
            by_machine.setdefault(row["设备编号"], []).append(row)
        for rows in by_machine.values():
            rows.sort(key=lambda r: (r["开始秒"], r["工序编号"]))
            previous_workshop = None
            previous_end = 0
            for row in rows:
                if previous_workshop is None:
                    travel = initial_travel_time(row["车间"])
                    origin = "班组1"
                else:
                    travel = travel_time(previous_workshop, row["车间"])
                    origin = previous_workshop
                row["运输起点"] = origin
                row["运输时间(s)"] = travel
                row["最早到达秒"] = previous_end + travel
                row["等待时间(s)"] = row["开始秒"] - row["最早到达秒"]
                previous_workshop = row["车间"]
                previous_end = row["结束秒"]

        assignment_rows.sort(key=lambda r: (r["开始秒"], r["设备编号"], r["工序编号"]))
        return operation_rows, assignment_rows


def choose_output_path(filename: str) -> Path:
    """若目标文件被Excel/WPS占用，则改用带时间戳的新文件名。"""
    path = ROOT / filename
    try:
        with path.open("a", encoding="utf-8"):
            pass
        return path
    except PermissionError:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        alternative = path.with_name(f"{path.stem}_{stamp}{path.suffix}")
        print(f"提示：{path.name} 正被其他程序占用，结果将另存为 {alternative.name}")
        return alternative


def write_results(operation_rows, assignment_rows, makespan, status_text, bound):
    schedule_path = choose_output_path("问题2_最优设备调度方案.csv")
    operation_path = choose_output_path("问题2_工序起止时间.csv")
    summary_path = choose_output_path("问题2_求解摘要.txt")

    assignment_fields = [
        "序号", "设备编号", "设备类型", "车间", "工序编号", "分配工程量",
        "起始时间", "结束时间", "持续工作时间(s)", "运输起点",
        "运输时间(s)", "等待时间(s)"
    ]
    with schedule_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=assignment_fields)
        writer.writeheader()
        for index, row in enumerate(assignment_rows, 1):
            writer.writerow(
                {
                    "序号": index,
                    "设备编号": row["设备编号"],
                    "设备类型": row["设备类型"],
                    "车间": row["车间"],
                    "工序编号": row["工序编号"],
                    "分配工程量": f'{row["分配工程量"]:.3f}',
                    "起始时间": fmt_time(row["开始秒"]),
                    "结束时间": fmt_time(row["结束秒"]),
                    "持续工作时间(s)": row["持续工作时间(s)"],
                    "运输起点": row["运输起点"],
                    "运输时间(s)": row["运输时间(s)"],
                    "等待时间(s)": row["等待时间(s)"],
                }
            )

    with operation_path.open("w", encoding="utf-8-sig", newline="") as f:
        fields = ["车间", "工序编号", "工序开始", "工序结束", "工序持续时间(s)"]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in operation_rows:
            writer.writerow(
                {
                    "车间": row["车间"],
                    "工序编号": row["工序编号"],
                    "工序开始": fmt_time(row["工序开始"]),
                    "工序结束": fmt_time(row["工序结束"]),
                    "工序持续时间(s)": row["工序持续时间"],
                }
            )

    gap = 0.0 if makespan == 0 else max(0.0, (makespan - bound) / makespan)
    summary = (
        f"求解状态：{status_text}\n"
        f"当前最优完工时间：{makespan} s（{fmt_time(makespan)}）\n"
        f"严格下界：{bound:.0f} s（{fmt_time(int(math.ceil(bound)))}）\n"
        f"相对最优间隙：{gap:.6%}\n"
    )
    summary_path.write_text(summary, encoding="utf-8")
    return schedule_path, operation_path, summary_path, summary


def validate_solution(operations, chains, operation_rows, assignment_rows, makespan):
    """不依赖CP-SAT内部约束，对导出的方案进行一次独立复核。"""
    op_result = {row["工序编号"]: row for row in operation_rows}
    op_data = {op.code: op for op in operations}

    # 车间内部严格工序链。
    for chain in chains.values():
        for previous, current in zip(chain, chain[1:]):
            assert (
                op_result[current]["工序开始"] >= op_result[previous]["工序结束"]
            ), f"工序先后约束失败：{previous}->{current}"

    # 每一设备类型均完整覆盖工程量，且并联时间计算正确。
    for op in operations:
        type_finish = []
        for requirement in op.requirements:
            rows = [
                row for row in assignment_rows
                if row["工序编号"] == op.code
                and row["设备类型"] == requirement.equipment_type
            ]
            assert rows, f"{op.code}缺少{requirement.equipment_type}"
            assert len(rows) <= EQUIPMENT_COUNTS[requirement.equipment_type]
            assert abs(sum(row["分配工程量"] for row in rows) - op.workload) < 1e-6
            expected = duration_seconds(op.workload, requirement.efficiency, len(rows))
            assert all(row["持续工作时间(s)"] == expected for row in rows)
            assert all(row["开始秒"] == op_result[op.code]["工序开始"] for row in rows)
            type_finish.append(rows[0]["结束秒"])
        assert max(type_finish) == op_result[op.code]["工序结束"]

    # 每台设备的相邻任务满足“不重叠+跨车间运输”约束。
    by_machine: Dict[str, List[dict]] = {}
    for row in assignment_rows:
        by_machine.setdefault(row["设备编号"], []).append(row)
    for machine, rows in by_machine.items():
        rows.sort(key=lambda r: (r["开始秒"], r["工序编号"]))
        previous_end = 0
        previous_workshop = None
        for row in rows:
            required_travel = (
                initial_travel_time(row["车间"])
                if previous_workshop is None
                else travel_time(previous_workshop, row["车间"])
            )
            assert row["开始秒"] >= previous_end + required_travel, (
                f"{machine}从{previous_workshop or '班组1'}到{row['车间']}运输时间不足"
            )
            previous_end = row["结束秒"]
            previous_workshop = row["车间"]

    final_end = max(op_result[chains[w][-1]]["工序结束"] for w in "ABCDE")
    assert final_end == makespan


def main():
    parser = argparse.ArgumentParser(description="B题问题2精确CP-SAT优化")
    parser.add_argument("--time-limit", type=float, default=300.0, help="最大求解时间（秒）")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="搜索线程数；默认1以保证同一最优方案可重复复现，设为8可加速但可能返回另一组等价最优排程",
    )
    parser.add_argument("--log-search", action="store_true", help="输出CP-SAT搜索日志")
    parser.add_argument(
        "--no-refine",
        action="store_true",
        help="仅优化最短总工期，不执行固定最优工期后的紧凑化次级优化",
    )
    args = parser.parse_args()

    scheduler = ExactScheduler(args.time_limit, args.workers, args.log_search)
    scheduler.build()
    solver, status = scheduler.solve()
    primary_status_text = solver.StatusName(status)
    print(f"主目标求解状态：{primary_status_text}")

    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise SystemExit("未找到可行解，请增加--time-limit后重试。")

    makespan = solver.Value(scheduler.makespan)
    bound = solver.BestObjectiveBound()
    status_text = primary_status_text

    # 在固定最短总工期后，最小化全部工序完成时刻之和，使排程更紧凑。
    # 次级目标不会改变主目标的全局最优性。
    if status == cp_model.OPTIMAL and not args.no_refine:
        scheduler.model.Add(scheduler.makespan == makespan)
        scheduler.model.Minimize(sum(scheduler.op_end.values()))
        refined_solver, refined_status = scheduler.solve()
        if refined_status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            solver = refined_solver
            refined_text = solver.StatusName(refined_status)
            status_text = f"{primary_status_text}（最短总工期）；{refined_text}（紧凑化）"
            print(f"次级紧凑化状态：{refined_text}")
        # 最短总工期已经由第一阶段证明，严格下界仍取第一阶段结果。
        bound = makespan

    operation_rows, assignment_rows = scheduler.extract(solver)
    validate_solution(
        scheduler.operations,
        scheduler.chains,
        operation_rows,
        assignment_rows,
        makespan,
    )
    print("独立可行性校验：通过")
    paths = write_results(
        operation_rows, assignment_rows, makespan, status_text, bound
    )
    print(paths[-1], end="")
    print("输出文件：")
    for path in paths[:-1]:
        print(path)

    print("\n各车间最终完工时刻：")
    for workshop in "ABCDE":
        final_code = scheduler.chains[workshop][-1]
        end = solver.Value(scheduler.op_end[final_code])
        print(f"{workshop}车间：{end} s（{fmt_time(end)}）")


if __name__ == "__main__":
    main()
