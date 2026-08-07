import streamlit as st
import pandas as pd
import pdfplumber
import re
from collections import defaultdict

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（运管主班/运控白班/运控夜班/补贴天数/休息天数）")

uploaded_file = st.file_uploader("上传PDF值班表", type=["pdf"])

# 人员配置
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

    with pdfplumber.open(uploaded_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if not tables:
            st.error("未检测到表格")
            st.stop()
        table = tables[0]
        df = pd.DataFrame(table)
        st.subheader("原始表格预览")
        st.dataframe(df.head(10))

        # 1. 查找表头行（原逻辑：同时包含"运行控制"和"运行管理"）
        header_row_idx = None
        for i, row in df.iterrows():
            row_str = " ".join([str(cell) for cell in row if cell])
            if "运行控制" in row_str and "运行管理" in row_str:
                header_row_idx = i
                break
        if header_row_idx is None:
            st.error("未找到包含'运行控制'和'运行管理'的表头")
            st.stop()

        headers = df.iloc[header_row_idx].fillna("").astype(str)
        col_mapping = {}  # {列索引: 岗位类型}
        for idx, header in enumerate(headers):
            if "运行控制" in header:
                col_mapping[idx] = "control"
            elif "运行管理" in header:
                col_mapping[idx] = "management"
            elif "运行计划" in header:
                col_mapping[idx] = "plan"

        # 2. 提取所有数据行（表头之后且包含“白”或“夜”）
        data_rows = []
        for i in range(header_row_idx + 1, len(df)):
            row = df.iloc[i].fillna("").astype(str)
            if any("白" in cell or "夜" in cell for cell in row if cell):
                data_rows.append(row)

        # 3. 配对白班和夜班（相邻两行，上行白班，下行夜班）
        schedules = []
        for i in range(0, len(data_rows) - 1, 2):
            day_row = data_rows[i]
            night_row = data_rows[i+1]
            if ("白" in str(day_row[0]) or "白班" in str(day_row[0])) and \
               ("夜" in str(night_row[0]) or "夜班" in str(night_row[0])):
                schedules.append({"day": day_row, "night": night_row})

        if not schedules:
            st.error("未识别到白班/夜班配对，请确认PDF格式为白班夜班分两行（如6月示例）")
            st.stop()

        # 4. 解析例外
        exceptions = set()
        if exception_text:
            for line in exception_text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    date_str = parts[0]
                    name = parts[1]
                    exceptions.add((date_str, name))

        # 5. 统计各项指标 + 休息天数
        all_persons = control_staff.union(management_staff)
        stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0, "rest_days": 0} for name in all_persons}
        attendance_records = {name: [] for name in all_persons}  # 每天是否出勤

        for idx, sch in enumerate(schedules):
            day_cells = sch["day"]
            night_cells = sch["night"]
            # 提取当前日期（从第一个单元格中找“X月X日”）
            date_cell = str(day_cells[0])
            date_match = re.search(r"(\d+月\d+日|\d+日)", date_cell)
            date_str = date_match.group(1) if date_match else f"第{idx+1}天"

            # 当天白班和夜班的人员集合（用于休息天数）
            day_people = set()
            night_people = set()

            for col_idx, role in col_mapping.items():
                day_name = day_cells[col_idx] if col_idx < len(day_cells) else ""
                night_name = night_cells[col_idx] if col_idx < len(night_cells) else ""
                day_name = day_name.strip()
                night_name = night_name.strip()

                if day_name:
                    day_people.add(day_name)
                if night_name:
                    night_people.add(night_name)

                # 统计班次（只统计all_persons中的名字）
                if day_name and night_name:
                    if role == "management":
                        if (date_str, day_name) not in exceptions:
                            stats[day_name]["consecutive"] += 1
                    else:
                        stats[day_name]["consecutive"] += 1
                elif day_name and not night_name:
                    stats[day_name]["pure_day"] += 1
                elif not day_name and night_name:
                    stats[day_name]["pure_night"] += 1

            # 记录每个人当天是否出勤
            for name in all_persons:
                attendance_records[name].append((name in day_people) or (name in night_people))

        # 计算总夜班（补贴天数）
        for name in all_persons:
            stats[name]["total_night"] = stats[name]["consecutive"] + stats[name]["pure_night"]

        # 计算休息天数：连续未出勤≥2天的，休息天数=连续天数-1
        for name in all_persons:
            rest = 0
            cnt = 0
            for present in attendance_records[name]:
                if not present:
                    cnt += 1
                else:
                    if cnt >= 2:
                        rest += (cnt - 1)
                    cnt = 0
            if cnt >= 2:
                rest += (cnt - 1)
            stats[name]["rest_days"] = rest

        # 6. 输出结果
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
            st.write("识别的列映射：", col_mapping)
            st.write("总天数：", len(schedules))
            st.write("例外列表：", exceptions)
