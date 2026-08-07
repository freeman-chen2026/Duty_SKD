import streamlit as st
import pandas as pd
import pdfplumber
import re
from collections import defaultdict

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（运管主班/运控白班/运控夜班/补贴天数/休息天数）")

uploaded_file = st.file_uploader("上传值班表（PDF或Excel）", type=["pdf", "xlsx", "xls"])

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

    exceptions = set()
    if exception_text:
        for line in exception_text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                exceptions.add((parts[0], parts[1]))

    schedules = []
    file_type = uploaded_file.type

    # ==================== Excel 解析 ====================
    if file_type in ["application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "application/vnd.ms-excel"]:
        df = pd.read_excel(uploaded_file, header=None)
        st.subheader("原始表格预览")
        st.dataframe(df.head(15))

        # 查找表头行（包含“运行管理”的行）
        header_idx = None
        for i, row in df.iterrows():
            row_str = " ".join([str(c) for c in row if pd.notna(c)])
            if "运行管理" in row_str:
                header_idx = i
                break

        if header_idx is None:
            st.error("未找到包含'运行管理'的表头")
            st.stop()

        # 构建列映射
        col_mapping = {}
        for idx, val in enumerate(df.iloc[header_idx]):
            val_str = str(val) if pd.notna(val) else ""
            if "运行管理" in val_str:
                col_mapping[idx] = "management"
            elif "运行计划" in val_str:
                col_mapping[idx] = "plan"
            elif "运行监控" in val_str:
                col_mapping[idx] = "control"
            elif "运行保障" in val_str:
                col_mapping[idx] = "control"

        # 提取数据行（从表头后第2行开始）
        data_start = header_idx + 2
        day_row = None
        date_str = ""

        for i in range(data_start, len(df)):
            row = df.iloc[i]
            first_cell = str(row[0]) if pd.notna(row[0]) else ""
            second_cell = str(row[1]) if pd.notna(row[1]) else ""

            # 判断是否为日期行（第一列包含“日”）
            if "日" in first_cell:
                # 提取日期
                date_match = re.search(r"(\d+月\d+日|\d+日)", first_cell)
                date_str = date_match.group(1) if date_match else first_cell
                # 第二列是“白”或“晚”
                if "白" in second_cell:
                    day_row = row
                elif "晚" in second_cell and day_row is not None:
                    # 配对：上一行是白班，当前行是夜班
                    day_people = set()
                    night_people = set()
                    for col_idx, role in col_mapping.items():
                        day_name = str(day_row[col_idx]).strip() if pd.notna(day_row[col_idx]) else ""
                        night_name = str(row[col_idx]).strip() if pd.notna(row[col_idx]) else ""
                        if day_name and day_name not in ["nan", "None", ""]:
                            day_people.add(day_name)
                        if night_name and night_name not in ["nan", "None", ""]:
                            night_people.add(night_name)
                    schedules.append({"date": date_str, "day": day_people, "night": night_people})
                    day_row = None

        if not schedules:
            st.error("未能从Excel解析到排班数据")
            st.stop()

    # ==================== PDF 解析 ====================
    else:
        with pdfplumber.open(uploaded_file) as pdf:
            all_text = ""
            for page in pdf.pages:
                all_text += page.extract_text() + "\n"

        lines = all_text.split("\n")
        day_shifts = []
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
            st.error("未识别到任何排班数据，请检查文件格式")
            st.stop()

    st.success(f"成功识别 {len(schedules)} 天的排班数据")

    # ==================== 统计 ====================
    all_persons = control_staff.union(management_staff)
    stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0, "rest_days": 0} for name in all_persons}
    attendance_records = {name: [] for name in all_persons}

    for sch in schedules:
        date_str = sch["date"]
        day_set = sch["day"]
        night_set = sch["night"]

        for name in all_persons:
            in_day = name in day_set
            in_night = name in night_set
            attendance_records[name].append(in_day or in_night)

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

    # ==================== 输出 ====================
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

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📌 运行控制/计划人员")
        control_df = result_df[result_df["姓名"].isin(control_staff)]
        st.dataframe(control_df, use_container_width=True, height=400)
    with col2:
        st.subheader("⚙️ 运行管理人员")
        management_df = result_df[result_df["姓名"].isin(management_staff)]
        st.dataframe(management_df, use_container_width=True, height=400)

    csv = result_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("📥 下载完整统计表 (CSV)", csv, "shift_statistics.csv", "text/csv")

    with st.expander("🔍 调试信息"):
        st.write("总天数：", len(schedules))
        st.write("前3天示例：", schedules[:3])
