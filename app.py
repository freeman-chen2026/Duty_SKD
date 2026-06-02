import streamlit as st
import pdfplumber
import re
from collections import defaultdict

st.set_page_config(page_title="值班连班统计", layout="wide")
st.title("📊 值班表连班统计工具")

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
    # 规则：一行中包含“白”或“晚”表示该行是白班或夜班，并且这一行的第一个词通常是星期几+日期
    day_shifts = []   # 元素: (日期字符串, 姓名列表)
    night_shifts = []

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # 检查是否包含白班或夜班标识
        if "白" in line and not "晚" in line:
            # 提取日期（例如“星期一 1日”或“星期一白”）
            date_match = re.search(r"(\d+月\d+日|\d+日)", line)
            date_str = date_match.group(1) if date_match else ""
            # 提取所有中文姓名（2-3个汉字，常见姓名）
            names = re.findall(r"[\u4e00-\u9fa5]{2,3}", line)
            # 过滤掉明显不是人名的词（如“星期一”、“运行控制”等）
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

    # 配对：白班和夜班按顺序一一对应（假设PDF中白班和夜班交替出现）
    schedules = []
    min_len = min(len(day_shifts), len(night_shifts))
    for i in range(min_len):
        date_day, day_names = day_shifts[i]
        date_night, night_names = night_shifts[i]
        # 使用白班的日期（通常更准确）
        date_str = date_day if date_day else date_night
        schedules.append({
            "date": date_str,
            "day": day_names,
            "night": night_names
        })

    if not schedules:
        st.error("未识别到任何班次数据，请检查PDF格式是否包含'白'和'晚'字样")
        st.stop()

    st.success(f"成功识别 {len(schedules)} 天的排班数据")

    # 统计连班天数
    stats = defaultdict(lambda: {"consecutive": 0})

    for sch in schedules:
        date_str = sch["date"]
        day_set = set(sch["day"])
        night_set = set(sch["night"])
        all_names = day_set.union(night_set)

        for name in all_names:
            # 判断是否连班：同一天同时出现在白班和夜班
            if name in day_set and name in night_set:
                if name in management_staff:
                    # 运行管理人员：默认连班，例外除外
                    if (date_str, name) not in exceptions:
                        stats[name]["consecutive"] += 1
                elif name in control_staff:
                    # 运行控制/计划人员：按实际连班统计
                    stats[name]["consecutive"] += 1
                # 其他人员忽略

    # 整理结果
    result_data = []
    for name in control_staff:
        if name in stats:
            result_data.append({"姓名": name, "连班天数": stats[name]["consecutive"]})
        else:
            result_data.append({"姓名": name, "连班天数": 0})
    # 也显示运行管理人员的结果（可选）
    for name in management_staff:
        if name in stats:
            result_data.append({"姓名": name, "连班天数": stats[name]["consecutive"]})
        else:
            result_data.append({"姓名": name, "连班天数": 0})

    result_df = pd.DataFrame(result_data).sort_values(by="姓名")
    st.subheader("📈 连班统计结果")
    st.dataframe(result_df)

    csv = result_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button("下载CSV", csv, "consecutive_shifts.csv", "text/csv")

    with st.expander("🔍 调试信息"):
        st.write("总天数：", len(schedules))
        st.write("前3天数据：", schedules[:3])
