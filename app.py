import streamlit as st
import pdfplumber
import re
from collections import defaultdict
import pandas as pd

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（连班/白班/夜班）")

uploaded_file = st.file_uploader("上传PDF值班表", type=["pdf"])

# 人员配置
default_control_staff = "陈宇鸣 周贤民 吴迪 王浩宇 林泓辰 陈育盛 钟洪达"
control_staff_input = st.text_input("运行控制/计划人员名单（空格分隔）", value=default_control_staff)
management_staff_input = st.text_input("运行管理人员名单（空格分隔）", value="周贤民 陈宇鸣 王浩宇 翟一帆 鲁翔伟 张光超")

exception_text = st.text_area(
    "例外（运行管理人员当天不是连班）",
    placeholder="每行一个：日期 姓名，例如：\n6月1日 周贤民\n6月5日 陈宇鸣"
)

if uploaded_file:
    control_staff = set(control_staff_input.strip().split())
    management_staff = set(management_staff_input.strip().split())

    # 解析例外
    exceptions = set()
    if exception_text:
        for line in exception_text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                date_str = parts[0]
                name = parts[1]
                exceptions.add((date_str, name))

    # 读取PDF文本
    with pdfplumber.open(uploaded_file) as pdf:
        all_text = ""
        for page in pdf.pages:
            all_text += page.extract_text() + "\n"

    lines = all_text.split("\n")

    # 提取每天的白班和夜班
    day_shifts = []   # (日期, [姓名])
    night_shifts = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        if "白" in line and "晚" not in line:
            date_match = re.search(r"(\d+月\d+日|\d+日)", line)
            date_str = date_match.group(1) if date_match else ""
            names = re.findall(r"[\u4e00-\u9fa5]{2,3}", line)
            filtered_names = [n for n in names if n not in ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日", "运行控制", "运行管理", "白班", "夜班", "带班主任"]]
            if filtered_names:
                day_shifts.append((date_str, filtered_names))
        elif "晚" in line:
            date_match = re.search(r"(\d+月\d+日|\d+日)", line)
            date_str = date_match.group(1) if date_match else ""
            names = re.findall(r"[\u4e00-\u9fa5]{2,3}", line)
            filtered_names = [n for n in names if n not in ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日", "运行控制", "运行管理", "白班", "夜班", "带班主任"]]
            if filtered_names:
                night_shifts.append((date_str, filtered_names))

    # 配对
    schedules = []
    min_len = min(len(day_shifts), len(night_shifts))
    for i in range(min_len):
        date_day, day_names = day_shifts[i]
        date_night, night_names = night_shifts[i]
        date_str = date_day if date_day else date_night
        schedules.append({
            "date": date_str,
            "day": set(day_names),
            "night": set(night_names)
        })

    if not schedules:
        st.error("未识别到任何班次数据，请检查PDF格式")
        st.stop()

    st.success(f"成功识别 {len(schedules)} 天的排班数据")

    # 初始化统计字典
    # 对于 control 人员和 management 人员分别统计
    all_persons = control_staff.union(management_staff)
    stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0} for name in all_persons}

    for sch in schedules:
        date_str = sch["date"]
        day_set = sch["day"]
        night_set = sch["night"]

        for name in all_persons:
            in_day = name in day_set
            in_night = name in night_set

            if in_day and in_night:
                # 连班
                if name in management_staff:
                    if (date_str, name) not in exceptions:
                        stats[name]["consecutive"] += 1
                else:  # control 人员按实际连班统计
                    stats[name]["consecutive"] += 1
            elif in_day and not in_night:
                # 纯白班
                stats[name]["pure_day"] += 1
            elif not in_day and in_night:
                # 纯夜班
                stats[name]["pure_night"] += 1

    # 计算总夜班 = 连班天数 + 纯夜班
    for name in all_persons:
        stats[name]["total_night"] = stats[name]["consecutive"] + stats[name]["pure_night"]

    # 转换为DataFrame
    result_data = []
    for name in all_persons:
        result_data.append({
            "姓名": name,
            "连班天数": stats[name]["consecutive"],
            "纯白班": stats[name]["pure_day"],
            "纯夜班": stats[name]["pure_night"],
            "总夜班": stats[name]["total_night"]
        })

    result_df = pd.DataFrame(result_data).sort_values(by="姓名")

    # 分两个子表显示（控制人员 & 管理人员）
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📌 运行控制/计划人员")
        control_df = result_df[result_df["姓名"].isin(control_staff)]
        st.dataframe(control_df, use_container_width=True, height=400)
    with col2:
        st.subheader("⚙️ 运行管理人员")
        management_df = result_df[result_df["姓名"].isin(management_staff)]
        st.dataframe(management_df, use_container_width=True, height=400)

    # 下载完整CSV
    csv = result_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载完整统计表 (CSV)", csv, "shift_statistics.csv", "text/csv")

    with st.expander("🔍 调试信息"):
        st.write("总天数：", len(schedules))
        st.write("前3天示例：", schedules[:3])
