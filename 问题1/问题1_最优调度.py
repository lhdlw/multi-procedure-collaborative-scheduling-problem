"""B题问题1：班组1完成A车间全部工序的全局最优调度。

默认口径：00:00:00 时设备位于班组1驻地，班组1到A车间400 m，
设备移动速度2 m/s，因此首批设备最早在200 s时开始作业。

主口径采用“同型多机并联均分”：同一工序可投入多台同类型设备，
该设备类型对应的总工程量由这些设备均分并行完成。本问题是严格工序链
A1 -> A2 -> A3，且三道工序使用的设备类型互不冲突。因此每个工序对
每种所需设备投入全部可用机器，再用关键路径最早开始调度，即可求得并
证明全局最优解。
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from typing import Dict, List, Sequence, Tuple


@dataclass(frozen=True)
class Requirement:
    equipment_type: str
    efficiency_m3_per_hour: float


@dataclass(frozen=True)
class Operation:
    code: str
    name: str
    workload_m3: float
    requirements: Tuple[Requirement, ...]


@dataclass
class EquipmentState:
    equipment_id: str
    equipment_type: str
    available_time: int


@dataclass(frozen=True)
class Assignment:
    operation_code: str
    equipment_id: str
    equipment_type: str
    assigned_workload_m3: float
    start: int
    end: int
    working_duration: int


OPERATIONS: Tuple[Operation, ...] = (
    Operation(
        code="A1",
        name="缺陷填补",
        workload_m3=300,
        requirements=(
            Requirement("精密灌装机", 200),
            Requirement("自动化输送臂", 250),
        ),
    ),
    Operation(
        code="A2",
        name="表面整平",
        workload_m3=500,
        requirements=(
            Requirement("高速抛光机", 100),
            Requirement("工业清洗机", 250),
        ),
    ),
    Operation(
        code="A3",
        name="强度检测",
        workload_m3=500,
        requirements=(Requirement("自动传感多功能机", 100),),
    ),
)


CREW1_EQUIPMENT_COUNTS: Dict[str, int] = {
    "自动化输送臂": 4,
    "工业清洗机": 5,
    "精密灌装机": 5,
    "自动传感多功能机": 1,
    "高速抛光机": 1,
}

CREW1_TO_A_DISTANCE_M = 400
MOVING_SPEED_M_PER_S = 2


def ceil_seconds(workload_m3: float, efficiency_m3_per_hour: float) -> int:
    """按题意将持续作业时间换算为秒并向上取整。"""
    return math.ceil(workload_m3 / efficiency_m3_per_hour * 3600)


def format_hms(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def build_equipment(initial_arrival_time: int) -> Dict[str, List[EquipmentState]]:
    """建立班组1设备；允许未立即使用的设备提前到A车间等待。"""
    equipment: Dict[str, List[EquipmentState]] = {}
    for equipment_type, count in CREW1_EQUIPMENT_COUNTS.items():
        equipment[equipment_type] = [
            EquipmentState(
                equipment_id=f"{equipment_type}1-{index}",
                equipment_type=equipment_type,
                available_time=initial_arrival_time,
            )
            for index in range(1, count + 1)
        ]
    return equipment


def solve(
    include_initial_transport: bool = True,
    parallel_same_type: bool = True,
):
    """使用关键路径最早开始算法求问题1的精确最优解。"""
    initial_travel = (
        math.ceil(CREW1_TO_A_DISTANCE_M / MOVING_SPEED_M_PER_S)
        if include_initial_transport
        else 0
    )
    equipment = build_equipment(initial_travel)

    assignments: List[Assignment] = []
    operation_times: List[Tuple[str, int, int]] = []
    predecessor_finish = initial_travel

    for operation in OPERATIONS:
        selected: List[Tuple[Requirement, EquipmentState, float, int]] = []
        for requirement in operation.requirements:
            candidates = equipment[requirement.equipment_type]
            if parallel_same_type:
                # 问题1中各工序所需类型互不冲突，全部同型设备投入不会
                # 影响后续工序；等量分配能最小化同型设备的最晚完成时间。
                chosen = list(candidates)
            else:
                # 备选旧口径：每类设备只派一台。
                chosen = [
                    min(candidates, key=lambda x: (x.available_time, x.equipment_id))
                ]

            workload_per_machine = operation.workload_m3 / len(chosen)
            duration = ceil_seconds(
                workload_per_machine, requirement.efficiency_m3_per_hour
            )
            for machine in chosen:
                selected.append(
                    (requirement, machine, workload_per_machine, duration)
                )

        # 同一工序所需设备同时开始，并且必须等待前一道工序完成。
        operation_start = max(
            predecessor_finish,
            max(machine.available_time for _, machine, _, _ in selected),
        )

        machine_finish_times = []
        for requirement, machine, assigned_workload, duration in selected:
            machine_finish = operation_start + duration
            assignments.append(
                Assignment(
                    operation_code=operation.code,
                    equipment_id=machine.equipment_id,
                    equipment_type=requirement.equipment_type,
                    assigned_workload_m3=assigned_workload,
                    start=operation_start,
                    end=machine_finish,
                    working_duration=duration,
                )
            )
            # 较快设备完成自己的全部工作量后即可释放。
            machine.available_time = machine_finish
            machine_finish_times.append(machine_finish)

        operation_finish = max(machine_finish_times)
        operation_times.append((operation.code, operation_start, operation_finish))
        predecessor_finish = operation_finish

    makespan = predecessor_finish
    return initial_travel, assignments, operation_times, makespan, parallel_same_type


def theoretical_lower_bound(
    initial_travel: int,
    parallel_same_type: bool = True,
) -> int:
    """严格串行链的完工时间下界。"""
    longest_required_times = []
    for operation in OPERATIONS:
        durations = []
        for req in operation.requirements:
            machine_count = (
                CREW1_EQUIPMENT_COUNTS[req.equipment_type]
                if parallel_same_type
                else 1
            )
            durations.append(
                ceil_seconds(
                    operation.workload_m3 / machine_count,
                    req.efficiency_m3_per_hour,
                )
            )
        longest_required_times.append(max(durations))
    return initial_travel + sum(longest_required_times)


def validate(
    initial_travel: int,
    assignments: Sequence[Assignment],
    operation_times: Sequence[Tuple[str, int, int]],
    makespan: int,
    parallel_same_type: bool,
) -> None:
    """校验前后约束、设备占用与最优性证书。"""
    assert operation_times[0][1] >= initial_travel
    for previous, current in zip(operation_times, operation_times[1:]):
        assert current[1] >= previous[2], "违反车间内部工序先后约束"

    by_equipment: Dict[str, List[Assignment]] = {}
    for row in assignments:
        by_equipment.setdefault(row.equipment_id, []).append(row)
    for rows in by_equipment.values():
        rows.sort(key=lambda x: x.start)
        for previous, current in zip(rows, rows[1:]):
            assert current.start >= previous.end, "同一设备发生时间重叠"

    lower_bound = theoretical_lower_bound(initial_travel, parallel_same_type)
    assert makespan == lower_bound, "可行解未达到理论下界，不能证明全局最优"


def print_result(
    initial_travel: int,
    assignments: Sequence[Assignment],
    operation_times: Sequence[Tuple[str, int, int]],
    makespan: int,
    parallel_same_type: bool,
) -> None:
    print("B题问题1：班组1完成A车间的全局最优调度")
    print(f"初始运输时间：{initial_travel} s ({format_hms(initial_travel)})")
    print()
    print(
        f"{'序号':<4}{'设备编号':<24}{'分配工程量(m³)':<16}"
        f"{'起始时间':<12}{'结束时间':<12}{'持续工作时间(s)':<18}{'工序编号':<8}"
    )
    for index, row in enumerate(assignments, 1):
        print(
            f"{index:<4}{row.equipment_id:<24}{row.assigned_workload_m3:<16.3f}"
            f"{format_hms(row.start):<12}"
            f"{format_hms(row.end):<12}{row.working_duration:<18}"
            f"{row.operation_code:<8}"
        )

    print("\n各工序整体起止时间：")
    for code, start, end in operation_times:
        print(
            f"{code}: {format_hms(start)} - {format_hms(end)}, "
            f"工序历时 {end - start} s"
        )

    lower_bound = theoretical_lower_bound(initial_travel, parallel_same_type)
    print(f"\n理论下界：{lower_bound} s ({format_hms(lower_bound)})")
    print(f"最短总时长：{makespan} s ({format_hms(makespan)})")
    print("可行解达到理论下界，因此该方案为全局最优解。")


def main() -> None:
    parser = argparse.ArgumentParser(description="求解B题问题1的全局最优调度")
    parser.add_argument(
        "--exclude-initial-transport",
        action="store_true",
        help="按不计班组驻地到A车间初始运输时间的备选口径计算",
    )
    parser.add_argument(
        "--single-machine-per-type",
        action="store_true",
        help="使用每道工序每种设备只派一台的备选口径",
    )
    args = parser.parse_args()

    result = solve(
        include_initial_transport=not args.exclude_initial_transport,
        parallel_same_type=not args.single_machine_per_type,
    )
    validate(*result)
    print_result(*result)


if __name__ == "__main__":
    main()
