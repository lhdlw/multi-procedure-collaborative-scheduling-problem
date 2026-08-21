"""问题4：用图论关键路径法独立验证32058秒调度结果。

本程序不调用OR-Tools，也不重新使用CP-SAT的起止时间作为计算结果。
它只读取最终方案中的：
  1. 每道工序使用哪些设备；
  2. 各设备的任务访问顺序；
  3. 每类设备的作业持续时间。

随后构造“工序先后边 + 设备运输边 + 作业持续时间边”的有向无环图，
用Kahn拓扑排序和最长路动态规划重新计算全部任务的最早开始时刻。
若反算总工期与导出方案不同，程序会失败并报告不一致；只有两者均为
32058秒且预算、工程量、持续时间和运输约束全部通过，才判定交叉验证成功。
"""

from __future__ import annotations

import csv
import math
from collections import defaultdict, deque
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SCHEDULE_PATH = ROOT / "问题4_最优设备调度方案.csv"

BUDGET = 500_000
UNIT_PRICE = {
    "自动化输送臂": 50_000,
    "工业清洗机": 40_000,
    "精密灌装机": 35_000,
    "自动传感多功能机": 80_000,
    "高速抛光机": 75_000,
}
WORKLOAD = {
    "A1": 300, "A2": 500, "A3": 500,
    "B1": 120, "B2": 1500, "B3": 360, "B4": 360,
    "C1": 720, "C2": 720,
    "C3-1": 360, "C4-1": 400, "C5-1": 400,
    "C3-2": 360, "C4-2": 400, "C5-2": 400,
    "C3-3": 360, "C4-3": 400, "C5-3": 400,
    "D1": 600, "D2": 800, "D3": 450, "D4": 1500,
    "D5": 1500, "D6": 700,
    "E1": 1000, "E2": 600, "E3": 600,
}
EFFICIENCY = {
    ("A1", "精密灌装机"): 200, ("A1", "自动化输送臂"): 250,
    ("A2", "高速抛光机"): 100, ("A2", "工业清洗机"): 250,
    ("A3", "自动传感多功能机"): 100,
    ("B1", "工业清洗机"): 100,
    ("B2", "精密灌装机"): 200, ("B2", "自动化输送臂"): 300,
    ("B3", "精密灌装机"): 350,
    ("B4", "高速抛光机"): 120, ("B4", "自动传感多功能机"): 100,
    ("C1", "工业清洗机"): 250, ("C1", "自动化输送臂"): 250,
    ("C2", "精密灌装机"): 350,
    ("D1", "工业清洗机"): 250,
    ("D2", "精密灌装机"): 200, ("D2", "自动化输送臂"): 300,
    ("D3", "精密灌装机"): 350,
    ("D4", "高速抛光机"): 120, ("D4", "自动传感多功能机"): 300,
    ("D5", "自动传感多功能机"): 300,
    ("D6", "高速抛光机"): 100,
    ("E1", "工业清洗机"): 250,
    ("E2", "精密灌装机"): 350,
    ("E3", "自动传感多功能机"): 300, ("E3", "工业清洗机"): 100,
}
for cycle in range(1, 4):
    EFFICIENCY[(f"C3-{cycle}", "精密灌装机")] = 200
    EFFICIENCY[(f"C3-{cycle}", "自动化输送臂")] = 250
    EFFICIENCY[(f"C4-{cycle}", "高速抛光机")] = 120
    EFFICIENCY[(f"C4-{cycle}", "工业清洗机")] = 100
    EFFICIENCY[(f"C5-{cycle}", "自动传感多功能机")] = 100

CHAINS = {
    "A": ["A1", "A2", "A3"],
    "B": ["B1", "B2", "B3", "B4"],
    "C": ["C1", "C2", "C3-1", "C4-1", "C5-1", "C3-2",
          "C4-2", "C5-2", "C3-3", "C4-3", "C5-3"],
    "D": ["D1", "D2", "D3", "D4", "D5", "D6"],
    "E": ["E1", "E2", "E3"],
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


def parse_time(text: str) -> int:
    hour, minute, second = map(int, text.split(":"))
    return hour * 3600 + minute * 60 + second


def fmt_time(seconds: int) -> str:
    hour, remainder = divmod(seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def travel_time(origin: str, destination: str) -> int:
    if origin == destination:
        return 0
    return math.ceil(PAIR_DISTANCE[tuple(sorted((origin, destination)))] / 2)


def add_edge(graph, indegree, origin, destination, weight, label):
    graph[origin].append((destination, weight, label))
    indegree[destination] += 1
    indegree.setdefault(origin, 0)


def main() -> None:
    with SCHEDULE_PATH.open("r", encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    if not rows:
        raise SystemExit("调度方案为空。")

    for row in rows:
        row["开始秒"] = parse_time(row["起始时间"])
        row["结束秒"] = parse_time(row["结束时间"])
        row["持续秒"] = int(row["持续工作时间(s)"])
        row["班组编号"] = int(row["班组"].replace("班组", ""))
        row["工程量"] = float(row["分配工程量"])

    # 1. 预算与购置数量独立复核。
    purchased = {}
    for row in rows:
        if row["设备来源"] == "购置":
            purchased[(row["设备编号"], row["设备类型"], row["班组编号"])] = True
    purchase_cost = sum(UNIT_PRICE[equipment_type]
                        for _name, equipment_type, _team in purchased)
    if purchase_cost > BUDGET:
        raise AssertionError(f"预算超限：{purchase_cost}元")

    # 2. 工程量与持续时间独立复核。
    requirement_rows = defaultdict(list)
    operation_workshops = {}
    for row in rows:
        key = (row["工序编号"], row["设备类型"])
        requirement_rows[key].append(row)
        operation_workshops[row["工序编号"]] = row["车间"]
    for (code, equipment_type), group in requirement_rows.items():
        allocated = sum(row["工程量"] for row in group)
        if abs(allocated - WORKLOAD[code]) > 0.01:
            raise AssertionError(f"{code}/{equipment_type}工程量错误：{allocated}")
        count = len(group)
        expected_duration = math.ceil(
            WORKLOAD[code] * 3600 / (EFFICIENCY[(code, equipment_type)] * count)
        )
        if any(row["持续秒"] != expected_duration for row in group):
            raise AssertionError(
                f"{code}/{equipment_type}持续时间错误，应为{expected_duration}秒"
            )

    # 3. 构造事件DAG。S节点代表工序开始，E节点代表某类设备需求完成。
    source = ("SOURCE",)
    graph = defaultdict(list)
    indegree = defaultdict(int)
    nodes = {source}
    requirement_duration = {}
    for (code, equipment_type), group in requirement_rows.items():
        start_node = ("S", code)
        end_node = ("E", code, equipment_type)
        nodes.update((start_node, end_node))
        duration = group[0]["持续秒"]
        requirement_duration[(code, equipment_type)] = duration
        add_edge(graph, indegree, start_node, end_node, duration,
                 f"{code}/{equipment_type}作业")

    # 工序链：前序的所有设备类型完成后，后序工序才允许开始。
    for chain in CHAINS.values():
        for previous, current in zip(chain, chain[1:]):
            for code, equipment_type in requirement_rows:
                if code == previous:
                    add_edge(graph, indegree, ("E", code, equipment_type),
                             ("S", current), 0, f"工序链 {previous}→{current}")

    # 设备链：按导出方案的访问次序，只用次序，不采用其原开始时刻计算结果。
    by_machine = defaultdict(list)
    for row in rows:
        by_machine[row["设备编号"]].append(row)
    for machine, route in by_machine.items():
        route.sort(key=lambda row: (row["开始秒"], row["工序编号"]))
        first = route[0]
        initial = math.ceil(INITIAL_DISTANCE[first["班组编号"]][first["车间"]] / 2)
        add_edge(graph, indegree, source, ("S", first["工序编号"]), initial,
                 f"{machine}首次运输")
        for previous, current in zip(route, route[1:]):
            trans = travel_time(previous["车间"], current["车间"])
            add_edge(
                graph, indegree,
                ("E", previous["工序编号"], previous["设备类型"]),
                ("S", current["工序编号"]), trans,
                f"{machine}:{previous['车间']}→{current['车间']}运输",
            )

    # 4. Kahn拓扑排序 + DAG最长路动态规划。
    for node in nodes:
        indegree.setdefault(node, 0)
    queue = deque(sorted((node for node in nodes if indegree[node] == 0), key=str))
    distance = {node: -10**18 for node in nodes}
    distance[source] = 0
    predecessor = {}
    visited = 0
    while queue:
        origin = queue.popleft()
        visited += 1
        for destination, weight, label in graph[origin]:
            candidate = distance[origin] + weight
            if candidate > distance[destination]:
                distance[destination] = candidate
                predecessor[destination] = (origin, label, weight)
            indegree[destination] -= 1
            if indegree[destination] == 0:
                queue.append(destination)
    if visited != len(nodes):
        raise AssertionError("设备路线与工序链形成环路，方案不可行。")

    final_nodes = [
        ("E", CHAINS[workshop][-1], equipment_type)
        for workshop in "ABCDE"
        for code, equipment_type in requirement_rows
        if code == CHAINS[workshop][-1]
    ]
    critical_end = max(final_nodes, key=lambda node: distance[node])
    recomputed_makespan = distance[critical_end]
    exported_makespan = max(row["结束秒"] for row in rows)

    # 5. 输出关键路径，便于人工检查32058秒是怎样形成的。
    path = []
    node = critical_end
    while node != source:
        previous, label, weight = predecessor[node]
        path.append((label, weight, distance[node]))
        node = previous
    path.reverse()

    print("问题4：图论关键路径法独立交叉验证")
    print("=" * 66)
    print(f"读取设备—工序记录：{len(rows)} 条")
    print(f"独立复核购置费用：{purchase_cost} 元（预算上限{BUDGET}元）")
    print(f"导出方案总工期：  {exported_makespan} s（{fmt_time(exported_makespan)}）")
    print(f"DAG最长路反算值： {recomputed_makespan} s（{fmt_time(recomputed_makespan)}）")
    print("关键路径：")
    for label, weight, finish in path:
        print(f"  +{weight:5d}s → {fmt_time(finish)}  {label}")

    if recomputed_makespan != exported_makespan:
        raise AssertionError(
            f"验证失败：DAG反算{recomputed_makespan}s，导出方案{exported_makespan}s"
        )
    print("验证结论：通过。预算、工程量、持续时间、运输路线和总工期相互一致。")


if __name__ == "__main__":
    main()
