import streamlit as st
import pandas as pd
import pdfplumber
import re
from collections import defaultdict

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（运管主班/运控白班/运控夜班/补贴天数/休息天数）")

uploaded_file = st.file_uploader("上传PDF值班表", type=["pdf"])

# 人员配置（新增）
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

        # ---- 1. 查找表头行（增强） ----
        header_row_idx = None
        for i, row in df.iterrows():
            row_str = " ".join([str(cell) for cell in row if cell])
            if "运行控制" in row_str or "运行管理" in row_str:
                header_row_idx = i
                break
        if header_row_idx is None:
            st.error("未找到包含'运行控制'或'运行管理'的表头")
            st.stop()

        # 提取该行的列标题
        headers = df.iloc[header_row_idx].fillna("").astype(str)
        col_mapping = {}
        for idx, header in enumerate(headers):
            if "运行控制" in header:
                col_mapping[idx] = "control"
            elif "运行管理" in header:
                col_mapping[idx] = "management"
            elif "运行计划" in header:
                col_mapping[idx] = "plan"

        # 如果没找到，尝试下一行（表头可能跨两行）
        if not col_mapping and header_row_idx + 1 < len(df):
            headers2 = df.iloc[header_row_idx+1].fillna("").astype(str)
            for idx, header in enumerate(headers2):
                if "运行控制" in header:
                    col_mapping[idx] = "control"
                elif "运行管理" in header:
                    col_mapping[idx] = "management"
                elif "运行计划" in header:
                    col_mapping[idx] = "plan"

        # ---- 2. 提取数据行（含白/夜） ----
        data_rows = []
        for i in range(header_row_idx + 1, len(df)):
            row = df.iloc[i].fillna("").astype(str)
            if any("白" in cell or "夜" in cell for cell in row if cell):
                data_rows.append(row)

        # ---- 3. 配对白班和夜班（支持同行和分行） ----
        schedules = []
        i = 0
        while i < len(data_rows):
            first_cell = str(data_rows[i][0]) if len(data_rows[i]) > 0 else ""
            has_white = "白" in first_cell or "白班" in first_cell
            has_night = "夜" in first_cell or "夜班" in first_cell

            if has_white and has_night:
                # 同行包含白夜（8月格式）：该行既当白班也当夜班
                schedules.append({"day": data_rows[i], "night": data_rows[i]})
                i += 1
            elif has_white and not has_night:
                # 只有白班，检查下一行是否为夜班
                if i + 1 < len(data_rows):
                    next_cell = str(data_rows[i+1][0]) if len(data_rows[i+1]) > 0 else ""
                    if "夜" in next_cell or "夜班" in next_cell:
                        schedules.append({"day": data_rows[i], "night": data_rows[i+1]})
                        i += 2
                    else:
                        # 下一行不是夜班，跳过
                        i += 1
                else:
                    i += 1
            else:
                i += 1

        if not schedules:
            st.error("未识别到白班/夜班配对，请检查PDF格式")
            st.stop()

        # ---- 4. 解析例外 ----
        exceptions = set()
        if exception_text:
            for line in exception_text.strip().split("\n"):
                parts = line.strip().split()
                if len(parts) >= 2:
                    date_str = parts[0]
                    name = parts[1]
                    exceptions.add((date_str, name))

        # ---- 5. 统计各项指标 + 休息天数 ----
        all_persons = control_staff.union(management_staff)
        stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0, "rest_days": 0} for name in all_persons}
        attendance_records = {name: [] for name in all_persons}  # 每天出勤布尔值

        for idx, sch in enumerate(schedules):
            day_cells = sch["day"]
            night_cells = sch["night"]

            # 提取日期
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

                # 统计班次
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

            # 记录每人当天是否出勤
            for name in all_persons:
                attendance_records[name].append((name in day_people) or (name in night_people))

        # 计算总夜班（补贴天数）
        for name in all_persons:
            stats[name]["total_night"] = stats[name]["consecutive"] + stats[name]["pure_night"]

        # 计算休息天数
        for name in all_persons:
            rest_days = 0
            count = 0
            for present in attendance_records[name]:
                if not present:
                    count += 1
                else:
                    if count >= 2:
                        rest_days += (count - 1)
                    count = 0
            if count >= 2:
                rest_days += (count - 1)
            stats[name]["rest_days"] = rest_days

        # ---- 6. 输出结果 ----
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
