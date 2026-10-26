import pandas as pd
import ast
from pathlib import Path
import re
import math
import unicodedata
from typing import List, Set, Dict
from concurrent.futures import ProcessPoolExecutor
import os
import numpy as np

# ==========================================
# 移植自 text_similarity.py 的相似度计算逻辑
# ==========================================

class TextSimilarityResult:
    """文本相似度结果类"""
    def __init__(self):
        self.jaccard: float = 0.0
        self.cosine: float = 0.0
        self.edit_distance: float = 0.0
        self.is_match: bool = False
        self.similarity: float = 0.0

def compare_text_similarity(text1: str, text2: str) -> TextSimilarityResult:
    """
    比较两段文本的相似度，支持多种算法
    """
    result = TextSimilarityResult()

    if text1 == "" and text2 == "":
        result.jaccard = 1.0
        result.cosine = 1.0
        result.edit_distance = 1.0
        result.is_match = True
        result.similarity = 1.0
        return result

    # 计算三种相似度
    jaccard = text_similarity_jaccard(text1, text2)
    cosine = text_similarity_cosine(text1, text2)
    edit_distance = text_similarity_edit_distance(text1, text2)

    # 计算平均值
    avg_similarity = (jaccard + cosine + edit_distance) / 3

    # 判断是否匹配（阈值0.6）
    threshold = 0.6
    is_match = avg_similarity >= threshold

    # 赋值结果
    result.jaccard = jaccard
    result.cosine = cosine
    result.edit_distance = edit_distance
    result.is_match = is_match
    result.similarity = avg_similarity

    return result

def text_similarity_jaccard(text1: str, text2: str) -> float:
    """使用Jaccard相似度计算两段文本的相似度"""
    if text1 == "" or text2 == "":
        return 0.0

    words1 = tokenize_text(text1)
    words2 = tokenize_text(text2)

    set1: Set[str] = set(words1)
    set2: Set[str] = set(words2)

    intersection = len(set1 & set2)
    union = len(set1 | set2)

    if union == 0:
        return 0.0

    return intersection / union

def text_similarity_cosine(text1: str, text2: str) -> float:
    """使用余弦相似度计算两段文本的相似度"""
    if text1 == "" or text2 == "":
        return 0.0

    words1 = tokenize_text(text1)
    words2 = tokenize_text(text2)

    counter1: Dict[str, int] = {}
    counter2: Dict[str, int] = {}

    for word in words1:
        counter1[word] = counter1.get(word, 0) + 1
    for word in words2:
        counter2[word] = counter2.get(word, 0) + 1

    all_words: Set[str] = set(counter1.keys()) | set(counter2.keys())

    dot_product = 0.0
    magnitude1 = 0.0
    magnitude2 = 0.0

    for word in all_words:
        freq1 = float(counter1.get(word, 0))
        freq2 = float(counter2.get(word, 0))

        dot_product += freq1 * freq2
        magnitude1 += freq1 * freq1
        magnitude2 += freq2 * freq2

    magnitude1 = math.sqrt(magnitude1)
    magnitude2 = math.sqrt(magnitude2)

    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0

    return dot_product / (magnitude1 * magnitude2)

def text_similarity_edit_distance(text1: str, text2: str) -> float:
    """使用编辑距离计算两段文本的相似度"""
    if text1 == "" and text2 == "":
        return 1.0

    distance = levenshtein_distance(text1, text2)
    max_len = max(len(text1), len(text2))

    if max_len == 0:
        return 1.0

    return 1.0 - (distance / max_len)

def levenshtein_distance(text1: str, text2: str) -> int:
    """计算两个字符串的Levenshtein编辑距离"""
    if text1 == "" and text2 == "":
        return 0
    if text1 == "":
        return len(text2)
    if text2 == "":
        return len(text1)

    m, n = len(text1), len(text2)
    distance = [[0] * (n + 1) for _ in range(m + 1)]

    for i in range(m + 1):
        distance[i][0] = i
    for j in range(n + 1):
        distance[0][j] = j

    for i in range(1, m + 1):
        for j in range(1, n + 1):
            cost = 0 if text1[i-1] == text2[j-1] else 1
            distance[i][j] = min(
                distance[i-1][j] + 1,
                distance[i][j-1] + 1,
                distance[i-1][j-1] + cost
            )

    return distance[m][n]

def tokenize_text(text: str) -> List[str]:
    """简单分词方法，处理中英文混合文本"""
    if text == "":
        return []

    text = text.strip()
    pattern = re.compile(r'[\s!"#$%&\'()*+,-./:;<=>?@[\\\]^_`{|}~·！￥%&*（）—+【】；：”“’。，、？…]+')
    words = pattern.split(text)

    result = []
    for word in words:
        word = word.strip()
        if not word:
            continue
        sub_words = split_mixed_text(word)
        result.extend(sub_words)

    return result

def split_mixed_text(text: str) -> List[str]:
    """处理中英文混合文本，中文按字分，英文/数字保留完整"""
    if text == "":
        return []

    result = []
    current_word = []
    last_type = 0  # 0:未知, 1:英文, 2:数字, 3:中文

    for char in text:
        current_type = 0
        if char.isascii() and char.isalpha():
            current_type = 1
        elif char.isdigit():
            current_type = 2
        elif is_chinese_char(char):
            current_type = 3

        if current_type == 3:
            if current_word:
                result.append(''.join(current_word))
                current_word = []
            result.append(char)
            last_type = 3
        elif current_type in (1, 2):
            if last_type not in (0, current_type, 3):
                if current_word:
                    result.append(''.join(current_word))
                    current_word = []
            current_word.append(char)
            last_type = current_type
        else:
            if current_word:
                result.append(''.join(current_word))
                current_word = []
            last_type = 0

    if current_word:
        result.append(''.join(current_word))

    return result

def is_chinese_char(char: str) -> bool:
    """判断字符是否为中文字符"""
    if len(char) != 1:
        return False
    return unicodedata.category(char) == 'Lo' and 'CJK' in unicodedata.name(char, '')

# ==========================================
# 核心验证逻辑（移动到顶层以支持多进程）
# ==========================================

def validate_row(row):
    """验证单行的两列数据是否完全对应"""
    # 先判断是否为无效数据（无需验证，直接标为无效）
    if str(row["is_right_parts"]).strip().lower() == "failed" or pd.isna(row["is_correct"]) or str(row["is_correct"]).strip() == "":
        return "无效"

    # 处理is_right_parts列（字符串转列表）
    try:
        bool_list = ast.literal_eval(str(row["is_right_parts"]))
        if not isinstance(bool_list, list) or not all(type(value) is bool for value in bool_list):
            return "N"
    except:
        return "N"

    # 处理is_correct列（分号分割为列表）
    s=str(row["is_correct"])
    str_list = re.split(r"[;,]",s)

    # 长度不一致直接判定不匹配
    if len(bool_list) != len(str_list):
        return "N"

    # 逐元素比对（True→yes，False→no，不区分大小写）
    for b, s in zip(bool_list, str_list):
        standardized_s = s.strip().lower()
        if (b is True and standardized_s != "yes") or (b is False and standardized_s != "no"):
            return "N"

    # 所有元素都匹配
    return "Y"

def calculate_similarity_column(row, col1, col2):
    # 先判断是否为无效数据（复用validate_row的判断逻辑）
    if str(row["is_right_parts"]).strip().lower() == "failed" or pd.isna(row["is_correct"]) or str(row["is_correct"]).strip() == "":
        return "-"

    val1 = row.get(col1)
    val2 = row.get(col2)

    # 处理 NaN
    if pd.isna(val1): val1 = ""
    if pd.isna(val2): val2 = ""

    # 转为字符串
    str1 = str(val1).strip()
    str2 = str(val2).strip()

    # 计算相似度
    sim_result = compare_text_similarity(str1, str2)
    return sim_result.similarity

def normalize_question_type(q_type):
    """
    将题型映射到标准分类
    """
    if pd.isna(q_type):
        return ""

    q_str = str(q_type).strip()

    # 预处理：
    # 1. 移除括号及括号内的内容 (支持中文括号和英文括号)
    q_str = re.sub(r'（.*?）', '', q_str)
    q_str = re.sub(r'\(.*?\)', '', q_str)

    # 2. 移除空白字符，统一小写
    clean_str = q_str.replace(" ", "").replace("\t", "").replace("\n", "").lower()

    # 映射规则
    if "单选" in clean_str or "single_choice" in clean_str:
        return "单选"
    if "多选" in clean_str or "multiple_choice" in clean_str:
        return "多选"
    if "单空" in clean_str or "single_blank" in clean_str:
        return "单空填空"
    if "多空" in clean_str or "multiple_blank" in clean_str:
        return "多空填空"
    if "填空" in clean_str or "fill_in_the_blank" in clean_str:
        if "多" in clean_str:
            return "多空填空"
        return "单空填空"
    if "判断" in clean_str or "true_false" in clean_str or "judgment" in clean_str:
        return "判断"
    if "排序" in clean_str or "sorting" in clean_str or "ordering" in clean_str:
        return "排序"
    if "配对" in clean_str or "matching" in clean_str:
        return "配对"
    if "简答" in clean_str or "short_answer" in clean_str:
        return "简答题"
    if "解答" in clean_str or "calculation" in clean_str or "comprehensive" in clean_str:
        return "解答题"
    if "写作" in clean_str or "writing" in clean_str or "composition" in clean_str:
        return "写作题"
    if "翻译" in clean_str or "translation" in clean_str:
        return "翻译题"
    if "主观" in clean_str:
        return "其他主观题"
    if "客观" in clean_str:
        return "其他客观题"

    return clean_str

def calculate_question_type_check(row):
    # 先判断是否为无效数据
    if str(row["is_right_parts"]).strip().lower() == "failed" or pd.isna(row["is_correct"]) or str(row["is_correct"]).strip() == "":
        return "-"

    col1 = "question_type"
    col2 = "question_type_标注"

    # 检查列是否存在
    if col1 not in row.index or col2 not in row.index:
        return "N"

    val1 = row[col1]
    val2 = row[col2]

    # 归一化处理
    norm1 = normalize_question_type(val1)
    norm2 = normalize_question_type(val2)

    if not norm1 or not norm2:
         return "Y" if norm1 == norm2 else "N"

    return "Y" if norm1 == norm2 else "N"

def count_right_parts(row):
    # 如果是无效行，直接返回-
    if str(row["is_right_parts"]).strip().lower() == "failed" or pd.isna(row["is_correct"]) or str(row["is_correct"]).strip() == "":
        return "-"

    def get_parsed_len(val):
        s_val = str(val).strip()
        # 1. 尝试解析为 Python 列表
        try:
            parsed = ast.literal_eval(s_val)
            if isinstance(parsed, list):
                return len(parsed)
        except:
            pass

        # 2. 尝试按分号分割
        if ';' in s_val:
            parts = [p for p in s_val.split(';') if p.strip()]
            return len(parts)

        # 3. 其他情况视为单项
        return 1

    len_right = get_parsed_len(row["is_right_parts"])
    len_correct = get_parsed_len(row["is_correct"])

    return "Y" if len_right == len_correct else "N"

def process_dataframe_chunk(chunk_df):
    """
    处理数据块的函数，用于多进程调用
    """
    # 1. 计算相似度
    similarity_pairs = [
        ("question", "question_标注", "题干文本相似度"),
        ("user_answer", "user_answer_标注", "手写答案相似度"),
        ("user_final_answer", "final_user_answer_标注", "手写最终答案相似度"),
        ("final_right_answer", "final_user_answer_标注", "解题最终答案相似度")
    ]

    for col1, col2, target_col in similarity_pairs:
        if col1 in chunk_df.columns and col2 in chunk_df.columns:
            chunk_df[target_col] = chunk_df.apply(lambda row: calculate_similarity_column(row, col1, col2), axis=1)

    # 2. 题型检查
    if "question_type" in chunk_df.columns and "question_type_标注" in chunk_df.columns:
        chunk_df["题型检查"] = chunk_df.apply(calculate_question_type_check, axis=1)

    # 3. 判题结果个数对
    chunk_df["判题结果个数对"] = chunk_df.apply(count_right_parts, axis=1)

    # 4. 生成"正确与否"
    chunk_df["正确与否"] = chunk_df.apply(validate_row, axis=1)

    return chunk_df

def validate_and_analyze_excel(file_path, output_path="result_with_validation.xlsx"):
    """
    读取Excel文件，验证is_right_parts和is_correct列的对应关系，生成验证结果并统计
    核心规则：
    1. 仅统计question_category列为"客观题"的行
    2. 排除is_right_parts为"failed"的行
    3. 排除is_correct为空（空值/空字符串）的行
    参数:
        file_path: 输入Excel文件的路径
        output_path: 输出包含验证结果的Excel文件路径
    """
    # 1. 读取Excel文件
    try:
        print(f"正在读取文件: {file_path}")
        df = pd.read_excel(file_path, engine="openpyxl")
    except FileNotFoundError:
        print(f"错误：找不到文件 {file_path}")
        return
    except Exception as e:
        print(f"读取文件出错：{str(e)}")
        return

    # 2. 检查必要列是否存在
    required_cols = ["is_right_parts", "is_correct"]
    missing_cols = [col for col in required_cols if col not in df.columns]
    if missing_cols:
        print(f"错误：Excel文件缺少必要列 {missing_cols}")
        return

    # 3. 多进程处理
    print("开始多进程并行处理...")

    # 确定进程数，默认为CPU核心数
    max_workers = os.cpu_count()
    # 如果数据量很小，不使用多进程
    if len(df) < 100:
        print("数据量较小，使用单进程处理")
        df_processed = process_dataframe_chunk(df)
    else:
        print(f"使用 {max_workers} 个进程进行并行计算")
        # 将DataFrame分割成多个chunks
        chunk_size = math.ceil(len(df) / max_workers)
        chunks = [df.iloc[i:i + chunk_size].copy() for i in range(0, len(df), chunk_size)]

        with ProcessPoolExecutor(max_workers=max_workers) as executor:
            # 并行执行
            results = list(executor.map(process_dataframe_chunk, chunks))

        # 合并结果
        df_processed = pd.concat(results)

    # 6. 保存结果到新Excel
    try:
        df_processed.to_excel(output_path, index=False, engine="openpyxl")
        print(f"✅ 结果已保存到：{output_path}")
    except Exception as e:
        print(f"❌ 保存文件出错：{str(e)}")
        return

    # 7. 统计全量数据（便于对比无效数据占比）
    total_all = len(df_processed)
    total_invalid = (df_processed["正确与否"] == "无效").sum()

    # 8. 打印统计信息
    print("\n===== 辅助统计（全量数据） =====")
    print(f"Excel总行数：{total_all}")
    print(f"全量无效行数（failed/空答案）：{total_invalid} 行")

# 主程序执行
if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    # Map arguments from run_multisubject.sh to what the script needs
    # The shell script passes: -gp, -vp, -sn, -op.
    # But this script only needs one input file (which is the result of 04) and one output file.
    # Assuming -op in shell script is the input file for this step (since 04 outputs to it),
    # and maybe we want to overwrite it or output to a new file.
    # However, let's just use explicit arguments for clarity.

    parser.add_argument("-ip", "--input_path", type=str, required=True, help="Input Excel path (result from step 04)")
    parser.add_argument("-op", "--output_path", type=str, required=True, help="Output Excel path")

    # Optional arguments to be compatible with shell script if needed, but better to fix shell script
    parser.add_argument("-gp", "--gt_path", type=str, help="Ignored")
    parser.add_argument("-vp", "--vis_path", type=str, help="Ignored")
    parser.add_argument("-sn", "--sheet_name", type=str, help="Ignored")

    args = parser.parse_args()

    INPUT_FILE = Path(args.input_path)
    OUTPUT_FILE = Path(args.output_path)

    if not INPUT_FILE.exists():
        print(f"输入文件不存在: {INPUT_FILE}")
        sys.exit(1)

    # 执行验证和分析
    validate_and_analyze_excel(INPUT_FILE, OUTPUT_FILE)
