import streamlit as st
import pandas as pd
import pdfplumber
import re
from collections import defaultdict

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（运管主班/运控白班/运控夜班/补贴天数/休息天数）")

uploaded_file = st.file_uploader("上传PDF值班表", type=["pdf"])

default_control_staff = "陈宇鸣 周贤民 吴迪 王浩宇 林泓辰 陈育盛 钟洪达"
control_staff_input = st.text_input("运行控制/计划人员名单（空格分隔）", value=default_control_staff)
management_staff_input = st.text_input("运行管理人员名单（空格分隔）", value="周贤民 陈宇鸣 王浩宇 翟一帆 鲁翔伟 张光超")

exception_text = st.text_area(
    "特殊情况（运行管理当天不是连班）",
    placeholder="每行一个：日期 姓名，例如：\n6月1日 周贤民\n6月5日 陈宇鸣"
)

if uploaded_file:
    control_staff = set(control_staff_input.strip().split())
    management_staff = set(management_staff_input.strip().split())
    exceptions = set()
    if exception_text:
        for line in exception_text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                exceptions.add((parts[0], parts[1]))

    # 1. 先尝试表格提取
    schedules = []
    with pdfplumber.open(uploaded_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if tables and tables[0]:
            df = pd.DataFrame(tables[0])
            st.subheader("原始表格预览")
            st.dataframe(df.head(10))

            # 查找表头：允许只含"运行控制"或"运行管理"
            header_idx = None
            for i, row in df.iterrows():
                row_str = " ".join([str(c) for c in row if c])
                if "运行控制" in row_str or "运行管理" in row_str:
                    header_idx = i
                    break

            if header_idx is not None:
                # 构建列映射（尝试两行）
                col_mapping = {}
                for offset in [0, 1]:
                    if header_idx + offset >= len(df):
                        break
                    row_vals = df.iloc[header_idx + offset].fillna("").astype(str)
                    for idx, val in enumerate(row_vals):
                        if "运行管理" in val:
                            col_mapping[idx] = "management"
                        elif "运行计划" in val:
                            col_mapping[idx] = "plan"
                        elif "运行控制" in val:
                            col_mapping[idx] = "control"
                    if col_mapping:
                        break

                if col_mapping:
                    # 提取数据行（含“白”或“夜”）
                    data_rows = []
                    for i in range(header_idx + 2, len(df)):
                        row = df.iloc[i].fillna("").astype(str)
                        if any("白" in c or "夜" in c for c in row if c):
                            data_rows.append(row)

                    # 配对并提取人员
                    i = 0
                    while i < len(data_rows):
                        first = str(data_rows[i][0]) if len(data_rows[i]) > 0 else ""
                        has_w = "白" in first
                        has_n = "夜" in first

                        if has_w and has_n:
                            # 同行包含白夜（8月格式）
                            day_set = set()
                            night_set = set()
                            for col_idx, role in col_mapping.items():
                                name = data_rows[i][col_idx].strip() if col_idx < len(data_rows[i]) else ""
                                if name:
                                    day_set.add(name)
                                    night_set.add(name)
                            schedules.append({"date": first, "day": day_set, "night": night_set})
                            i += 1
                        elif has_w and not has_n:
                            if i + 1 < len(data_rows):
                                next_first = str(data_rows[i+1][0]) if len(data_rows[i+1]) > 0 else ""
                                if "夜" in next_first:
                                    day_set = set()
                                    night_set = set()
                                    for col_idx, role in col_mapping.items():
                                        day_name = data_rows[i][col_idx].strip() if col_idx < len(data_rows[i]) else ""
                                        night_name = data_rows[i+1][col_idx].strip() if col_idx < len(data_rows[i+1]) else ""
                                        if day_name:
                                            day_set.add(day_name)
                                        if night_name:
                                            night_set.add(night_name)
                                    schedules.append({"date": first, "day": day_set, "night": night_set})
                                    i += 2
                                    continue
                            i += 1
                        else:
                            i += 1

    # 如果表格提取失败，回退到文本解析
    if not schedules:
        st.warning("表格提取未能生成有效数据，尝试文本解析...")
        with pdfplumber.open(uploaded_file) as pdf:
            all_text = ""
            for page in pdf.pages:
                all_text += page.extract_text() + "\n"
        lines = all_text.split("\n")
        day_dict = {}
        night_dict = {}
        for line in lines:
            line = line.strip()
            if not line:
                continue
            date_match = re.search(r"(\d+月\d+日|\d+日)", line)
            if not date_match:
                continue
            date = date_match.group(1)
            names = re.findall(r"[\u4e00-\u9fa5]{2,3}", line)
            filter_words = ["星期一","星期二","星期三","星期四","星期五","星期六","星期日",
                            "运行控制","运行管理","白班","夜班","带班主任","运行计划","运行监控","运行保障"]
            names = [n for n in names if n not in filter_words]
            if not names:
                continue
            if "白" in line and "晚" in line:
                split = len(names)//2
                day_dict[date] = set(names[:split])
                night_dict[date] = set(names[split:])
            elif "白" in line:
                day_dict[date] = set(names)
            elif "晚" in line:
                night_dict[date] = set(names)
        for date in sorted(set(day_dict.keys()) & set(night_dict.keys())):
            schedules.append({"date": date, "day": day_dict[date], "night": night_dict[date]})

    if not schedules:
        st.error("未能识别任何排班数据，请检查PDF格式。")
        st.stop()

    st.success(f"成功识别 {len(schedules)} 天的排班数据")

    # 统计各项指标
    all_persons = control_staff.union(management_staff)
    stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0, "rest_days": 0} for name in all_persons}
    attendance = {name: [] for name in all_persons}

    for sch in schedules:
        date_str = sch["date"]
        day_set = sch["day"]
        night_set = sch["night"]

        for name in all_persons:
            in_day = name in day_set
            in_night = name in night_set
            attendance[name].append(in_day or in_night)

            if in_day and in_night:
                if name in management_staff:
                    if (date_str, name) not in exceptions:
                        stats[name]["consecutive"] += 1
                else:
                    stats[name]["consecutive"] += 1
            elif in_day and not in_night:
                stats[name]["pure_day"] += 1
            elif not in_day and in_night:
                stats[name]["pure_night"] += 1

    for name in all_persons:
        stats[name]["total_night"] = stats[name]["consecutive"] + stats[name]["pure_night"]

    # 休息天数
    for name in all_persons:
        rest = 0
        cnt = 0
        for present in attendance[name]:
            if not present:
                cnt += 1
            else:
                if cnt >= 2:
                    rest += (cnt - 1)
                cnt = 0
        if cnt >= 2:
            rest += (cnt - 1)
        stats[name]["rest_days"] = rest

    # 输出结果
    result_data = []
    for name in all_persons:
        result_data.append({
            "姓名": name,
            "运管主班": stats[name]["consecutive"],
            "运控白班": stats[name]["pure_day"],
            "运控夜班": stats[name]["pure_night"],
            "补贴天数": stats[name]["total_night"],
            "休息天数": stats[name]["rest_days"]
        })
    result_df = pd.DataFrame(result_data).sort_values(by="运管主班", ascending=False)
    st.subheader("📈 统计结果")
    st.dataframe(result_df)

    csv = result_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("下载CSV", csv, "shift_statistics.csv", "text/csv")

    with st.expander("🔍 调试信息"):
        st.write("识别的天数：", len(schedules))
        st.write("前3天示例：", schedules[:3])
