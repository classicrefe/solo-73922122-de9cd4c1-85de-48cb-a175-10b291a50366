"""solver 的本地测试。运行：python3 -I tests/run_tests.py
通过 tests/stub 下的 networkx 替身加载 solver，验证解析、校验与可行性求解。
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "stub"))       # networkx 替身优先
sys.path.insert(0, os.path.join(HERE, "..", "app"))  # solver 模块

import solver  # noqa: E402

PASSED = FAILED = 0


def check(name, cond, detail=""):
    global PASSED, FAILED
    if cond:
        PASSED += 1
        print(f"  PASS {name}")
    else:
        FAILED += 1
        print(f"  FAIL {name} {detail}")


def pipes(rows):
    return [
        {"id": r[0], "start": r[1], "end": r[2], "lower": r[3], "upper": r[4]}
        for r in rows
    ]


def verify_solution(result, source, sink):
    """独立复核：区间、整数、内部节点守恒、供水量一致。"""
    flows = result["flows"]
    for f in flows:
        if not (isinstance(f["value"], int) and f["lower"] <= f["value"] <= f["upper"]):
            return False, f"管段 {f['id']} 读数越界"
    net = {}
    for f in flows:
        net[f["start"]] = net.get(f["start"], 0) - f["value"]
        net[f["end"]] = net.get(f["end"], 0) + f["value"]
    for n, b in net.items():
        if n not in (source, sink) and b != 0:
            return False, f"内部节点 {n} 不守恒（净流 {b}）"
    if net.get(source, 0) != -result["total_supply"]:
        return False, "总供水量与源点净流出不符"
    if net.get(sink, 0) != result["total_supply"]:
        return False, "汇点净流入与总供水量不符"
    return True, ""


def expect_feasible(name, rows, source, sink):
    r = solver.solve(pipes(rows), source, sink)
    if not r["feasible"]:
        check(name, False, "应可行但报不可行")
        return
    ok, why = verify_solution(r, source, sink)
    check(name, ok, why)


def expect_infeasible(name, rows, source, sink):
    r = solver.solve(pipes(rows), source, sink)
    check(name, not r["feasible"], "应不可行但报可行")


def expect_error(name, fn, keyword=""):
    try:
        fn()
    except solver.InputError as e:
        check(name, keyword in str(e), f"消息不含「{keyword}」: {e}")
    except Exception as e:  # noqa: BLE001
        check(name, False, f"抛出了非 InputError: {type(e).__name__}: {e}")
    else:
        check(name, False, "应抛 InputError 但未抛")


print("== 可行性求解 ==")
expect_feasible(
    "基本可行网络",
    [("P1", "S", "A", 0, 10), ("P2", "S", "B", 2, 5), ("P3", "A", "B", 0, 3),
     ("P4", "A", "T", 0, 10), ("P5", "B", "T", 0, 6)],
    "S", "T",
)
expect_feasible(
    "下界迫使绕行",
    [("P1", "S", "A", 4, 6), ("P2", "S", "B", 0, 10),
     ("P3", "A", "T", 0, 10), ("P4", "B", "T", 4, 8)],
    "S", "T",
)
expect_feasible(
    "全零下界零流可行",
    [("P1", "S", "A", 0, 5), ("P2", "A", "T", 0, 5)],
    "S", "T",
)
expect_feasible(
    "平行管段",
    [("P1", "S", "T", 3, 4), ("P2", "S", "T", 2, 9)],
    "S", "T",
)
expect_infeasible(
    "出口容量不足",
    [("P1", "S", "A", 5, 10), ("P2", "A", "T", 0, 3)],
    "S", "T",
)
expect_infeasible(
    "内部节点守恒无法满足",
    [("P1", "S", "A", 5, 5), ("P2", "A", "B", 0, 2), ("P3", "B", "T", 0, 9)],
    "S", "T",
)
expect_infeasible(
    "下界总量超过汇端承接",
    [("P1", "S", "A", 6, 9), ("P2", "S", "B", 4, 9),
     ("P3", "A", "T", 0, 5), ("P4", "B", "T", 0, 4)],
    "S", "T",
)

print("== 输入与拓扑校验 ==")
expect_error(
    "下限大于上限",
    lambda: solver.solve(pipes([("P1", "S", "T", 5, 2)]), "S", "T"),
    "区间非法",
)
expect_error(
    "存在有向环",
    lambda: solver.solve(
        pipes([("P1", "S", "A", 0, 1), ("P2", "A", "B", 0, 1),
               ("P3", "B", "A", 0, 1), ("P4", "B", "T", 0, 1)]), "S", "T"),
    "有向环",
)
expect_error(
    "节点数超限",
    lambda: solver.solve(
        pipes([(f"P{i}", f"N{i}", f"N{i+1}", 0, 1) for i in range(9)]), "N0", "N9"),
    "节点数",
)
expect_error(
    "管段数超限",
    lambda: solver.solve(
        pipes([(f"P{i}", "S", "T", 0, 1) for i in range(13)]), "S", "T"),
    "超过上限",
)
expect_error(
    "源汇相同",
    lambda: solver.solve(pipes([("P1", "S", "T", 0, 1)]), "S", "S"),
    "不能相同",
)
expect_error(
    "源点不在数据中",
    lambda: solver.solve(pipes([("P1", "S", "T", 0, 1)]), "X", "T"),
    "未出现",
)
expect_error(
    "节点游离于源汇通路之外",
    lambda: solver.solve(
        pipes([("P1", "S", "T", 0, 5), ("P2", "A", "B", 0, 3)]), "S", "T"),
    "拓扑错误",
)

print("== CSV 解析 ==")
r = solver.solve(
    solver.parse_csv("管段编号,起点,终点,流量下限,流量上限\nP1,S,A,0,10\nP2,A,T,1,4\n"),
    "S", "T",
)
check("中文表头解析", r["feasible"])

r = solver.solve(solver.parse_csv("P1,S,A,0,10\nP2,A,T,1,4\n"), "S", "T")
check("无表头按位置解析", r["feasible"])

r = solver.solve(
    solver.parse_csv("id,from,to,lower,upper\nP1,S,A,0,10\nP2,A,T,0,4\n"), "S", "T"
)
check("英文表头解析", r["feasible"])

expect_error(
    "负下界",
    lambda: solver.parse_csv("P1,S,T,-1,5\n"),
    "非负整数",
)
expect_error(
    "小数上界",
    lambda: solver.parse_csv("P1,S,T,0,2.5\n"),
    "非负整数",
)
expect_error(
    "编号重复",
    lambda: solver.parse_csv("P1,S,A,0,1\nP1,A,T,0,1\n"),
    "重复",
)
expect_error(
    "自环",
    lambda: solver.parse_csv("P1,S,S,0,1\n"),
    "自环",
)
expect_error(
    "空 CSV",
    lambda: solver.parse_csv("  \n\n"),
    "为空",
)

print(f"\n通过 {PASSED} 项，失败 {FAILED} 项")
sys.exit(1 if FAILED else 0)
