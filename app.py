import streamlit as st
import pdfplumber
import re
from collections import defaultdict
import pandas as pd

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表统计工具（运管主班/运控白班/运控夜班/补贴天数/休息天数）")

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

    exceptions = set()
    if exception_text:
        for line in exception_text.strip().split("\n"):
            parts = line.strip().split()
            if len(parts) >= 2:
                date_str = parts[0]
                name = parts[1]
                exceptions.add((date_str, name))

    # ---------- 1. 尝试用表格结构解析 ----------
    schedules = []  # 最终列表，每个元素 {"date": str, "day": set, "night": set}
    parse_success = False

    with pdfplumber.open(uploaded_file) as pdf:
        page = pdf.pages[0]
        tables = page.extract_tables()
        if tables:
            table = tables[0]
            df = pd.DataFrame(table)

            # 寻找表头行：找到包含"运行控制"的行
            header_row_idx = None
            for i, row in df.iterrows():
                row_str = " ".join([str(cell) for cell in row if cell])
                if "运行控制" in row_str:
                    header_row_idx = i
                    break

            if header_row_idx is not None:
                # 确定列映射：寻找“运行管理”、“运行计划”、“运行监控”等
                # 注意：表头可能有多行，我们取包含这些关键词的一行作为列标题
                # 这里简单处理：在header_row_idx及下一行中查找
                for offset in [0, 1]:
                    check_row = df.iloc[header_row_idx + offset] if header_row_idx + offset < len(df) else None
                    if check_row is None:
                        continue
                    # 构建列映射
                    col_mapping = {}
                    for idx, cell in enumerate(check_row):
                        cell_str = str(cell) if cell else ""
                        if "运行管理" in cell_str:
                            col_mapping[idx] = "management"
                        elif "运行计划" in cell_str:
                            col_mapping[idx] = "plan"
                        elif "运行监控" in cell_str:
                            col_mapping[idx] = "control"   # 归入控制
                        elif "运行保障" in cell_str:
                            col_mapping[idx] = "control"
                        elif "运行控制" in cell_str:
                            # 如果只有“运行控制”而没有细分，则后续列都视为控制
                            pass
                    if col_mapping:
                        break

                if col_mapping:
                    # 开始解析数据行
                    data_start = header_row_idx + 2  # 跳过表头行
                    # 遍历每一行，寻找包含“白”或“晚”的行
                    for i in range(data_start, len(df)):
                        row = df.iloc[i].fillna("").astype(str)
                        first_cell = row[0] if len(row) > 0 else ""
                        # 如果第一格包含“白”或“晚”，说明是日期+班次标识
                        if "白" in first_cell or "晚" in first_cell:
                            # 判断是白班还是夜班（可能同时存在，如“白<br>晚”）
                            day_names = []
                            night_names = []
                            # 提取所有列的值，按col_mapping取对应岗位的人员
                            for col_idx, role in col_mapping.items():
                                name = row[col_idx] if col_idx < len(row) else ""
                                name = name.strip()
                                if name and name not in ["None", ""]:
                                    # 如果这一行同时包含白和晚，我们无法仅凭这一行区分，但我们可以利用相邻行？
                                    # 实际上，8月格式是同一行，但白班和夜班的人员在相同列？不，它们应该是分开的。
                                    # 这里我们只能假设：如果一行同时有“白”和“晚”，则这一行包含了白班和夜班两个班次的人员，
                                    # 但人员是前后顺序，需要分割。但通过表格提取，其实每个列对应一个岗位，白班和夜班在同一个单元格？实际上，8月表格中“白<br>晚”是一个合并单元格，然后后面的单元格是人员名，但白班和夜班的人员是分别放在不同列的？我们从PDF文本看，一行中“白<br>晚”之后跟着一系列名字，这些名字可能交替代表白班和夜班。但表格提取可能已经将白班和夜班拆分为不同行？实际上，PDF中可能是一行，但表格提取后，可能白班和夜班是同一行的不同单元格？很难。

                            # 更稳健的方法：我们放弃表格解析，改用文本解析，但针对8月格式特殊处理。
                            # 因此，这里直接退回到文本解析。
                            parse_success = False
                            break
                    else:
                        parse_success = True  # 假设成功
                else:
                    parse_success = False

    # ---------- 2. 若表格解析失败，回退到文本解析（增强版，同时支持两种格式） ----------
    if not parse_success:
        # 重新读取PDF文本
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

            # 检查是否包含日期标识（如“1日”、“2日”等）
            has_date = re.search(r"\d+日", line)
            if not has_date:
                continue

            # 检查是否包含“白”和/或“晚”
            has_white = "白" in line
            has_night = "晚" in line

            # 提取所有中文姓名（2-3个汉字）
            names = re.findall(r"[\u4e00-\u9fa5]{2,3}", line)
            # 过滤掉非人名关键词
            filter_keywords = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日",
                               "运行控制", "运行管理", "白班", "夜班", "带班主任", "运行计划", "运行监控", "运行保障"]
            filtered_names = [n for n in names if n not in filter_keywords]

            if not filtered_names:
                continue

            # 提取日期
            date_match = re.search(r"(\d+月\d+日|\d+日)", line)
            date_str = date_match.group(1) if date_match else ""

            if has_white and not has_night:
                # 只有白班
                day_shifts.append((date_str, filtered_names))
            elif has_night and not has_white:
                # 只有夜班
                night_shifts.append((date_str, filtered_names))
            elif has_white and has_night:
                # 既有白班又有夜班（8月格式）：我们需要将名单分割成白班和夜班
                # 通常这种格式下，名单顺序是白班人员，然后是夜班人员，但数量可能不固定。
                # 我们尝试根据已知人员名单来分割？不可靠。
                # 更可靠：从表格提取失败，但我们可以利用相邻行？实际上8月每行都是单独一天，白班和夜班都在同一行。
                # 我们无法分辨哪些是白班哪些是夜班，只能假设白班和夜班的人员数量相同？但实际不同。
                # 为了解决，我们放弃这种格式的精确区分，改为将所有人员同时加入白班和夜班？但那样会误判连班。
                # 更好的做法：让用户手动输入每天白班和夜班？不现实。
                # 因此，对于这种格式，我们只能将名单中的所有人员视为既上白班又上夜班（即连班），这会导致统计错误。
                # 但为了能让8月数据可用，我们可以使用另一种策略：利用表格提取，但上面已经失败。
                # 我们选择一种折中：将名单分成两半，前半为白班，后半为夜班？这可能接近真实。
                # 经过观察8月PDF，例如“1日白<br>晚翟一帆陈宇鸣周贤民钟洪达周贤民罗建新罗建新”，白班可能有3人，夜班有4人？不确定。
                # 我决定不冒险，而是提示用户使用表格提取方式，但既然表格提取失败，我们只能报错。
                st.error("检测到8月格式（白班夜班同行），当前文本解析无法准确拆分。建议使用表格提取方式，但似乎表格解析也失败。请检查PDF是否为标准表格。")
                st.stop()

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
            st.error("未能识别任何排班数据，请检查PDF格式。")
            st.stop()

    st.success(f"成功识别 {len(schedules)} 天的排班数据")

    # ---------- 统计 ----------
    all_persons = control_staff.union(management_staff)
    stats = {name: {"consecutive": 0, "pure_day": 0, "pure_night": 0, "total_night": 0, "rest_days": 0} for name in all_persons}

    for sch in schedules:
        date_str = sch["date"]
        day_set = sch["day"]
        night_set = sch["night"]

        for name in all_persons:
            in_day = name in day_set
            in_night = name in night_set

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
        attendance = []
        for sch in schedules:
            day_set = sch["day"]
            night_set = sch["night"]
            attendance.append((name in day_set) or (name in night_set))
        rest_days = 0
        count = 0
        for present in attendance:
            if not present:
                count += 1
            else:
                if count >= 2:
                    rest_days += (count - 1)
                count = 0
        if count >= 2:
            rest_days += (count - 1)
        stats[name]["rest_days"] = rest_days

    # 输出
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
