# -*- coding: utf-8 -*-
"""
三角洲行动 —— 动态爆率平衡机制 计算系统（完整版）
========================================================
完整实现文档中推导的公式：

    P_final = min( P_base × F_history × F_raid × F_events , P_cap )

其中：
    F_history = α·F_kd + β·F_pratio
    F_raid    = Factor_search × Factor_wealth × Factor_combat
    F_events  = 1 + θ_damage·(1 - D_taken) + θ_killstreak·S

特性：
  1. 交互式输入附带「游戏内对照说明」
  2. 计算完成后自动生成「提升爆率建议」，并按潜在收益排序
  3. 程序结束前会暂停，按回车才退出（方便双击 exe 使用）

运行方式：
    python loot_system.py            # 场景演示 + 交互式输入
    python loot_system.py --demo     # 只运行场景对比
    python loot_system.py --all      # 同默认
"""

import math
import copy
import argparse
from typing import Dict, List


# ============================================================
# 核心计算类
# ============================================================
class DeltaActionLootSystem:
    """
    三角洲行动战利品爆率计算系统

    实现了基于玩家历史数据、当局表现和事件影响的动态爆率计算模型。
    """

    def __init__(self):
        # ---------- 基础概率（地图初始值） ----------
        self.base_rates = {
            "red": 0.005,     # 红色品质基础概率 0.5%
            "gold": 0.025,    # 金色品质基础概率 2.5%
            "purple": 0.1,    # 紫色品质基础概率 10%
        }

        # ---------- 概率上限（安全阀） ----------
        self.probability_caps = {
            "red": 0.03,      # 红色品质概率上限 3%
            "gold": 0.08,     # 金色品质概率上限 8%
            "purple": 0.25,   # 紫色品质概率上限 25%
        }

        # ---------- 系统常量 ----------
        self.constants = {
            "K_avg": 1.0,              # 服务器平均 KD
            "P_ideal": 1.2,            # 理想赚损比
            "alpha": 0.6,              # 历史 KD 权重
            "beta": 0.4,               # 历史赚损比权重
            "gamma": 0.15,             # KD 历史增益强度
            "delta": 0.2,              # 赚损比历史增益强度
            "epsilon": 0.03,           # 容器搜索增益系数
            "zeta": 0.1,               # 实时赚损增益系数
            "eta": 0.1,                # 当局战斗表现增益系数
            "theta_damage": 0.05,      # 受伤影响系数
            "theta_killstreak": 0.02,  # 连续击杀影响系数
        }

        # ---------- 默认玩家数据 ----------
        self.default_player = {
            "historical": {
                "kd_ratio": 1.0,
                "profit_ratio": 1.0,
            },
            "current_raid": {
                "kd_ratio": 1.0,
                "profit_ratio": 1.0,
                "containers_searched": 0,
                "damage_taken": 0.0,
                "kill_streak": 0,
            },
        }

    # --------------------------------------------------------
    # 工具方法
    # --------------------------------------------------------
    def new_player_data(self) -> Dict:
        """返回一份全新的玩家数据模板（深拷贝）"""
        return copy.deepcopy(self.default_player)

    @staticmethod
    def _clamp(value: float, low: float, high: float) -> float:
        """把数值限制在 [low, high] 区间内"""
        return max(low, min(high, value))

    # --------------------------------------------------------
    # 系数计算
    # --------------------------------------------------------
    def calculate_historical_factor(self, player_data: Dict) -> float:
        """
        计算历史调整系数 F_history（挫折保护机制）

        F_kd      = 1 + γ · max(0, (K_avg - K) / K_avg)
        F_pratio  = 1 + δ · max(0, (P_ideal - P_hist) / P_ideal)
        F_history = α · F_kd + β · F_pratio
        """
        c = self.constants
        kd = player_data["historical"]["kd_ratio"]
        profit_ratio = player_data["historical"]["profit_ratio"]

        kd_diff = max(0.0, (c["K_avg"] - kd) / c["K_avg"])
        f_kd = 1 + c["gamma"] * kd_diff

        profit_diff = max(0.0, (c["P_ideal"] - profit_ratio) / c["P_ideal"])
        f_pratio = 1 + c["delta"] * profit_diff

        return c["alpha"] * f_kd + c["beta"] * f_pratio

    def calculate_raid_factor(self, player_data: Dict) -> float:
        """
        计算当局表现系数 F_raid

        Factor_search = 1 + ε · ln(1 + C_searched)          （边际效应递减）
        Factor_wealth = 1 + ζ · P_ratio_raid                （线性增长，无饱和）
        Factor_combat = 1 + η · (2/π) · atan(K_raid)        （饱和式战斗奖励）

        F_raid = Factor_search × Factor_wealth × Factor_combat
        """
        c = self.constants
        raid = player_data["current_raid"]

        search_factor = 1 + c["epsilon"] * math.log(1 + raid["containers_searched"])
        wealth_factor = 1 + c["zeta"] * raid["profit_ratio"]
        combat_factor = 1 + c["eta"] * (2 / math.pi) * math.atan(raid["kd_ratio"])

        return search_factor * wealth_factor * combat_factor

    def calculate_events_factor(self, player_data: Dict) -> float:
        """
        计算事件影响系数 F_events

        F_events = 1 + θ_damage · (1 - D_taken) + θ_killstreak · S
        注：本实现按公式 (1 - D_taken) 计算，即剩余生命比例越高，事件奖励越大。
        """
        c = self.constants
        raid = player_data["current_raid"]

        damage_bonus = c["theta_damage"] * (1 - raid["damage_taken"])
        streak_bonus = c["theta_killstreak"] * raid["kill_streak"]

        return 1 + damage_bonus + streak_bonus

    # --------------------------------------------------------
    # 最终概率
    # --------------------------------------------------------
    def calculate_final_probability(self, player_data: Dict, item_quality: str) -> float:
        """计算指定品质物品的最终爆率"""
        base_prob = self.base_rates[item_quality]
        cap = self.probability_caps[item_quality]

        f_history = self.calculate_historical_factor(player_data)
        f_raid = self.calculate_raid_factor(player_data)
        f_events = self.calculate_events_factor(player_data)

        final_prob = base_prob * f_history * f_raid * f_events
        return min(final_prob, cap)

    def calculate_all_probabilities(self, player_data: Dict) -> Dict[str, float]:
        """一次性计算红 / 金 / 紫三种品质的爆率"""
        return {
            "red": self.calculate_final_probability(player_data, "red"),
            "gold": self.calculate_final_probability(player_data, "gold"),
            "purple": self.calculate_final_probability(player_data, "purple"),
        }

    @staticmethod
    def format_probability(prob: float) -> str:
        """把 0~1 的概率格式化成百分比字符串"""
        return f"{prob * 100:.4f}%"

    # --------------------------------------------------------
    # 输出：计算详情
    # --------------------------------------------------------
    def print_calculation_details(self, player_data: Dict) -> None:
        """打印完整的计算过程与结果"""
        print("=" * 64)
        print("三角洲行动战利品爆率计算系统")
        print("=" * 64)

        hist = player_data["historical"]
        raid = player_data["current_raid"]

        print("\n【玩家数据】")
        print(f"  历史 KD          : {hist['kd_ratio']:.2f}")
        print(f"  历史赚损比       : {hist['profit_ratio']:.2f}")
        print(f"  当局 KD          : {raid['kd_ratio']:.2f}")
        print(f"  当局赚损比       : {raid['profit_ratio']:.2f}")
        print(f"  搜索容器数       : {raid['containers_searched']}")
        print(f"  受伤程度         : {raid['damage_taken'] * 100:.1f}%")
        print(f"  连杀数           : {raid['kill_streak']}")

        f_history = self.calculate_historical_factor(player_data)
        f_raid = self.calculate_raid_factor(player_data)
        f_events = self.calculate_events_factor(player_data)

        print("\n【计算系数】")
        print(f"  历史调整系数 F_history : {f_history:.4f}")
        print(f"  当局表现系数 F_raid    : {f_raid:.4f}")
        print(f"  事件影响系数 F_events  : {f_events:.4f}")
        print(f"  综合调整系数           : {f_history * f_raid * f_events:.4f}")

        probabilities = self.calculate_all_probabilities(player_data)

        print("\n【最终爆率】")
        for quality, prob in probabilities.items():
            base = self.base_rates[quality]
            cap = self.probability_caps[quality]
            capped = "  <-- 已触发上限" if prob >= cap - 1e-12 else ""
            print(f"  {quality.upper():<7}品质: {self.format_probability(prob):>10}"
                  f"   (基础 {self.format_probability(base)}"
                  f" / 上限 {self.format_probability(cap)}){capped}")

        print("=" * 64)

    # --------------------------------------------------------
    # 输出：提升建议
    # --------------------------------------------------------
    def _build_suggestions(self, player_data: Dict) -> List[Dict]:
        """
        根据当前数据生成「提升爆率」的建议列表。
        每条建议包含：title、potential（系数潜在增量）、detail（具体说明）
        """
        c = self.constants
        raid = player_data["current_raid"]

        # 各子因子当前值
        search_factor = 1 + c["epsilon"] * math.log(1 + raid["containers_searched"])
        wealth_factor = 1 + c["zeta"] * raid["profit_ratio"]
        combat_factor = 1 + c["eta"] * (2 / math.pi) * math.atan(raid["kd_ratio"])
        damage_bonus = c["theta_damage"] * (1 - raid["damage_taken"])
        streak_bonus = c["theta_killstreak"] * raid["kill_streak"]

        # 各方向「还能提升多少」的系数增量（估算，用于排序）
        wealth_potential = c["zeta"] * max(0.0, 3.0 - raid["profit_ratio"])
        search_potential = c["epsilon"] * max(
            0.0, math.log(31) - math.log(1 + raid["containers_searched"]))
        combat_potential = c["eta"] * (2 / math.pi) * max(
            0.0, math.atan(5.0) - math.atan(raid["kd_ratio"]))
        damage_potential = c["theta_damage"] * raid["damage_taken"]
        streak_potential = c["theta_killstreak"] * max(0, 5 - raid["kill_streak"])

        suggestions: List[Dict] = []

        # ---- 1. 实时财富 ----
        if wealth_potential > 0.01:
            suggestions.append({
                "title": "提高当局赚损比（收益最稳定）",
                "potential": wealth_potential,
                "detail": (
                    f"当前当局赚损比 {raid['profit_ratio']:.2f}，财富因子 {wealth_factor:.4f}。\n"
                    f"       财富因子是线性增长、无饱和的，每提升 1.0 赚损比，\n"
                    f"       约增加 {c['zeta'] * 100:.0f}% 的最终爆率。\n"
                    f"       → 敢于携带高价值装备入局，努力把带出价值做到带入价值的 2~3 倍以上。"
                ),
            })

        # ---- 2. 搜索容器 ----
        if search_potential > 0.005:
            suggestions.append({
                "title": "多搜索容器（开局前 10 个收益最大）",
                "potential": search_potential,
                "detail": (
                    f"当前搜索 {raid['containers_searched']} 个容器，搜索因子 {search_factor:.4f}。\n"
                    f"       搜索因子是对数增长，前 10 个容器收益最大，超过 20 个后收益快速递减。\n"
                    f"       → 开局先快速搜 10~15 个高价值容器，性价比最高。"
                ),
            })

        # ---- 3. 战斗表现 ----
        if combat_potential > 0.005:
            suggestions.append({
                "title": "适度提升战斗表现",
                "potential": combat_potential,
                "detail": (
                    f"当前当局 KD {raid['kd_ratio']:.2f}，战斗因子 {combat_factor:.4f}。\n"
                    f"       战斗因子采用反正切函数，KD 达到 2~3 后收益就基本饱和了。\n"
                    f"       → 不需要刻意追求高 KD，KD 达到 2~3 即可拿到大部分收益，剩下靠财富和搜索。"
                ),
            })

        # ---- 4. 保持血量 ----
        if damage_potential > 0.005:
            suggestions.append({
                "title": "尽量保持高血量撤离",
                "potential": damage_potential,
                "detail": (
                    f"当前受伤程度 {raid['damage_taken'] * 100:.0f}%，事件奖励 {damage_bonus:.4f}。\n"
                    f"       程序按「剩余生命比例」给予奖励，满血撤离该项最大（+0.05）。\n"
                    f"       → 撤离前尽量保持健康，少掉血。"
                ),
            })

        # ---- 5. 连杀 ----
        if streak_potential > 0.005:
            suggestions.append({
                "title": "尝试打出连杀",
                "potential": streak_potential,
                "detail": (
                    f"当前连杀 {raid['kill_streak']} 次，连杀奖励 {streak_bonus:.4f}。\n"
                    f"       每次未被中断的连续击杀提供 +{c['theta_killstreak'] * 100:.0f}% 的最终爆率。\n"
                    f"       → 交火中注意保命，累积连杀能叠加额外奖励。"
                ),
            })

        # 按潜在增量从高到低排序
        suggestions.sort(key=lambda x: x["potential"], reverse=True)
        return suggestions

    def print_suggestions(self, player_data: Dict) -> None:
        """打印提升爆率的建议"""
        print()
        print("=" * 64)
        print("提升爆率建议")
        print("=" * 64)

        probs = self.calculate_all_probabilities(player_data)
        capped_items = [q for q, p in probs.items()
                        if p >= self.probability_caps[q] - 1e-12]

        if capped_items:
            names = "/".join(q.upper() for q in capped_items)
            print(f"\n[!] 注意：{names} 品质的爆率已触发上限，")
            print("    再怎么堆加成也不会超过天花板。以下建议针对未触发上限的部分。\n")

        suggestions = self._build_suggestions(player_data)

        if not suggestions:
            print("\n[√] 各项表现都已经非常出色，没有明显的提升空间了。")
            print("    保持当前节奏就好。")
            print("=" * 64)
            return

        print(f"\n根据算法分析，最值得提升的方向（共 {len(suggestions)} 条，按收益排序）：\n")

        for i, sug in enumerate(suggestions, 1):
            print(f"  {i}. 【{sug['title']}】")
            print(f"     潜在提升 ≈ 综合系数 +{sug['potential']:.4f}"
                  f"（约相当于最终爆率 +{sug['potential'] * 100:.2f}%）")
            print(f"     {sug['detail']}")
            print()

        print("=" * 64)
        print("说明：")
        print("  · 财富因子和搜索因子是主要提升空间，战斗因子很快饱和。")
        print("  · 所有提升最终仍受概率上限约束，无法突破天花板。")
        print()


# ============================================================
# 辅助函数：快速构造玩家数据
# ============================================================
def make_player(hist_kd: float = 1.0,
                hist_profit: float = 1.0,
                raid_kd: float = 1.0,
                raid_profit: float = 1.0,
                containers: int = 0,
                damage: float = 0.0,
                streak: int = 0) -> Dict:
    """根据参数快速生成一份玩家数据结构"""
    return {
        "historical": {
            "kd_ratio": hist_kd,
            "profit_ratio": hist_profit,
        },
        "current_raid": {
            "kd_ratio": raid_kd,
            "profit_ratio": raid_profit,
            "containers_searched": containers,
            "damage_taken": damage,
            "kill_streak": streak,
        },
    }


# ============================================================
# 场景演示
# ============================================================
def run_scenarios(system: DeltaActionLootSystem) -> None:
    """跑一组预设场景，直观对比不同玩家行为的爆率差异"""
    scenarios = [
        ("基准玩家（全部默认）", make_player()),
        ("新手挫折保护（低KD / 长期亏损）",
         make_player(hist_kd=0.4, hist_profit=0.6)),
        ("高手玩家（高KD / 高收益）",
         make_player(hist_kd=3.0, hist_profit=2.0)),
        ("单局疯狂搜刮（30容器 + 收益翻倍）",
         make_player(containers=30, raid_profit=2.0, raid_kd=2.0)),
        ("残血连杀撤离（高风险高光操作）",
         make_player(containers=15, raid_profit=1.8, raid_kd=3.0,
                     damage=0.85, streak=5)),
        ("极端拉满（触发概率上限）",
         make_player(hist_kd=0.3, hist_profit=0.5, raid_kd=10.0,
                     raid_profit=30.0, containers=1000,
                     damage=0.95, streak=10)),
    ]

    print()
    print("=" * 100)
    print("场景对比演示")
    print("=" * 100)
    print(f"{'场景':<34}{'F_hist':>9}{'F_raid':>9}{'F_event':>9}"
          f"{'红色爆率':>12}{'金色爆率':>12}{'紫色爆率':>12}")
    print("-" * 100)

    for name, data in scenarios:
        f_h = system.calculate_historical_factor(data)
        f_r = system.calculate_raid_factor(data)
        f_e = system.calculate_events_factor(data)
        probs = system.calculate_all_probabilities(data)

        print(f"{name:<34}{f_h:>9.4f}{f_r:>9.4f}{f_e:>9.4f}"
              f"{system.format_probability(probs['red']):>12}"
              f"{system.format_probability(probs['gold']):>12}"
              f"{system.format_probability(probs['purple']):>12}")

    print("=" * 100)
    print("说明：")
    print("  · F_history 只对低于平均水平的玩家产生增益（挫折保护），高手保持 1.0。")
    print("  · F_raid 鼓励搜索容器、局内致富与击杀，但受对数 / 反正切曲线抑制。")
    print("  · 所有结果都会被 P_cap 硬性截断，保证顶级物资的稀有性。")
    print()


# ============================================================
# 交互式演示
# ============================================================
def _ask(prompt: str, default, cast):
    """安全读取一个输入，回车或非法输入时返回默认值"""
    try:
        raw = input(prompt).strip()
    except EOFError:
        print()
        return default
    if raw == "":
        return default
    try:
        return cast(raw)
    except (ValueError, TypeError):
        print(f"  [!] 输入无效，使用默认值：{default}")
        return default


def interactive_demo(system: DeltaActionLootSystem) -> None:
    """交互式输入玩家数据并计算爆率"""
    print()
    print("=" * 64)
    print("三角洲行动战利品爆率计算系统 —— 交互式演示")
    print("直接回车使用默认值")
    print("=" * 64)

    player_data = system.new_player_data()
    hist = player_data["historical"]
    raid = player_data["current_raid"]

    # ---------- 历史数据 ----------
    print("\n[历史数据]  游戏内位置：主界面左上角头像 →「个人信息」")
    print("---------------------------------------------------------")
    hist["kd_ratio"] = _ask(
        f"  历史 KD 比（看'战损比'字段，如 1.25）[默认 {hist['kd_ratio']}]: ",
        hist["kd_ratio"], float)
    hist["profit_ratio"] = _ask(
        f"  历史赚损比（看'赚损比'，去掉 M/K 单位，如 1.4M→填 1.4）[默认 {hist['profit_ratio']}]: ",
        hist["profit_ratio"], float)

    # ---------- 当局数据 ----------
    print("\n[当局数据]  本局的表现，可在结算界面或历史战绩里查看")
    print("---------------------------------------------------------")
    raid["kd_ratio"] = _ask(
        f"  当局 KD 比（结算界面右下'战损比'）[默认 {raid['kd_ratio']}]: ",
        raid["kd_ratio"], float)
    raid["profit_ratio"] = _ask(
        f"  当局赚损比（带出价值÷带入价值，如带出200万/带入50万=4.0）[默认 {raid['profit_ratio']}]: ",
        raid["profit_ratio"], float)
    raid["containers_searched"] = _ask(
        f"  搜索容器数量（本局开了多少个箱子，自己数）[默认 {raid['containers_searched']}]: ",
        raid["containers_searched"], int)
    damage = _ask(
        f"  受伤程度 0~1（0=满血撤离，0.5=半血，0.9=丝血）[默认 {raid['damage_taken']}]: ",
        raid["damage_taken"], float)
    raid["damage_taken"] = system._clamp(float(damage), 0.0, 1.0)
    raid["kill_streak"] = _ask(
        f"  连杀数（本局未中断的连续击杀，全程没死过才算连杀）[默认 {raid['kill_streak']}]: ",
        raid["kill_streak"], int)

    # 兜底：负数 / 非法值修正
    raid["containers_searched"] = max(0, int(raid["containers_searched"]))
    raid["kill_streak"] = max(0, int(raid["kill_streak"]))
    raid["kd_ratio"] = max(0.0, float(raid["kd_ratio"]))
    raid["profit_ratio"] = max(0.0, float(raid["profit_ratio"]))
    hist["kd_ratio"] = max(0.0, float(hist["kd_ratio"]))
    hist["profit_ratio"] = max(0.0, float(hist["profit_ratio"]))

    # ---------- 输出结果 ----------
    print()
    system.print_calculation_details(player_data)
    system.print_suggestions(player_data)


# ============================================================
# 入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="三角洲行动 —— 动态爆率平衡机制计算系统")
    parser.add_argument("--demo", action="store_true",
                        help="只运行场景对比演示，不进入交互模式")
    parser.add_argument("--all", action="store_true",
                        help="先运行场景演示，再进入交互模式")
    args = parser.parse_args()

    system = DeltaActionLootSystem()

    try:
        if args.demo:
            run_scenarios(system)
        else:
            run_scenarios(system)
            interactive_demo(system)
    except KeyboardInterrupt:
        print("\n\n[已中断]")

    # ---- 暂停，等用户按回车再退出 ----
    # 解决双击 exe 时窗口一闪而过的问题
    try:
        input("\n按回车键退出...")
    except EOFError:
        # 如果输入被重定向（如 CMD 里管道输入），则忽略
        pass


if __name__ == "__main__":
    main()