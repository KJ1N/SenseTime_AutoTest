#将图片文件夹转URL
import tempfile
import argparse
import re
from stat import FILE_ATTRIBUTE_NORMAL
import sys
import os
import time
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)
import base64
import pandas as pd
from pathlib import Path
import oss2
#from utils.image_utils2 import get_sorted_image_files_by_number
from oss2.models import CorsRule, BucketCors
#from utils.image_merge import find_and_merge_paired_images

# OSS配置
config = {
    "access_key_id": os.getenv("OSS_ACCESS_KEY_ID", ""),
    "access_key_secret": os.getenv("OSS_ACCESS_KEY_SECRET", ""),
    "endpoint": os.getenv("OSS_ENDPOINT", ""),
    "bucket_name": os.getenv("OSS_BUCKET_NAME", ""),
    "prefix": os.getenv("OSS_PREFIX", "evaluation")
}

def get_sorted_image_files_by_number(input_data):
    """
    获取按数字排序的图片文件列表【兼容双入参】
    :param input_data: 支持两种入参 → ① 文件夹路径字符串 ② 文件列表(list)，列表元素可为「纯文件名」或「完整文件路径」
    支持多种文件名格式:
    - 纯数字: 1.jpg, 2.jpg, 10.jpg
    - page格式: page01.jpeg, page02.jpeg
    - page_q格式: page01_q01.png, page01_q02.png, page02_q01.png
    - 其他带前缀: img_001.jpg
    按照文件名中的数字排序，返回结构不变
    """
    # ===================== 核心兼容逻辑 - 自动识别入参类型 =====================
    files = []
    directory_path = ""
    # 情况1: 入参是【文件夹路径字符串】→ 原逻辑，读取目录下所有图片文件
    if isinstance(input_data, str) and os.path.isdir(input_data):
        directory_path = input_data
        files = [f for f in os.listdir(directory_path) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
    # 情况2: 入参是【文件列表】→ 兼容 纯文件名列表 / 完整文件路径列表
    elif isinstance(input_data, list) and len(input_data) > 0:
        for file_item in input_data:
            if isinstance(file_item, str):
                # 如果是完整路径，只提取文件名用于匹配规则；如果是纯文件名，直接使用
                file_name = os.path.basename(file_item)
                # 过滤非图片文件，保留原过滤规则
                if file_name.lower().endswith(('.jpg', '.jpeg', '.png')):
                    files.append(file_item)
                    # 自动提取目录路径（如果传入的是完整路径）
                    if os.path.dirname(file_item) and not directory_path:
                        directory_path = os.path.dirname(file_item)

    # ===================== 原逻辑完全保留 - 解析文件名并排序 =====================
    file_info = []
    for file_item in files:
        # 统一提取【纯文件名】用于正则匹配（兼容完整路径/纯文件名）
        filename = os.path.basename(file_item)

        # 1. 先尝试匹配纯数字文件名，如 1.jpg, 2.jpg, 10.jpg
        match = re.match(r'^(\d+)\.(jpg|jpeg|png)$', filename, re.IGNORECASE)
        if match:
            file_number = int(match.group(1))  # 文件名中的数字
            file_info.append({
                'filename': filename,
                'file_number': file_number,
                'page_number': 0,  # 纯数字格式没有页码
                'question_number': 0,  # 纯数字格式没有题号
                'full_path': os.path.join(directory_path, filename) if directory_path else file_item
            })
        else:
            # 2. 尝试匹配 page{数字}_q{数字} 格式，如 page01_q01.png, page02_q01.png
            match = re.match(r'^page(\d+)_q(\d+)(?:\(\d+\))?\.(jpg|jpeg|png)$', filename, re.IGNORECASE)
            if match:
                page_number = int(match.group(1))  # page后面的数字
                question_number = int(match.group(2))  # q后面的数字
                # 使用 page_number * 1000 + question_number 作为排序键，确保先按页码再按题号排序
                file_number = page_number * 1000 + question_number
                file_info.append({
                    'filename': filename,
                    'file_number': file_number,
                    'page_number': page_number,
                    'question_number': question_number,
                    'full_path': os.path.join(directory_path, filename) if directory_path else file_item
                })
            else:
                # 3. 尝试匹配 page{数字} 格式，如 page01.jpeg, page02.jpeg
                match = re.match(r'^page(\d+)\.(jpg|jpeg|png)$', filename, re.IGNORECASE)
                if match:
                    file_number = int(match.group(1))  # page后面的数字
                    file_info.append({
                        'filename': filename,
                        'file_number': file_number,
                        'page_number': file_number,
                        'question_number': 0,
                        'full_path': os.path.join(directory_path, filename) if directory_path else file_item
                    })
                else:
                    # 4. 尝试匹配文件名末尾的数字，如 img_001.jpg, xxx_123.png
                    match = re.search(r'(\d+)\.(jpg|jpeg|png)$', filename, re.IGNORECASE)
                    if match:
                        file_number = int(match.group(1))  # 文件名中的数字
                        file_info.append({
                            'filename': filename,
                            'file_number': file_number,
                            'page_number': 0,
                            'question_number': 0,
                            'full_path': os.path.join(directory_path, filename) if directory_path else file_item
                        })

    # 按照数字排序
    file_info.sort(key=lambda x: x['file_number'])

    return file_info

def merge_images_vertically(img1_path, img2_path, output_path):
    """
    将两张图片垂直拼接（img1在上，img2在下）
    :param img1_path: 上方图片路径
    :param img2_path: 下方图片路径
    :param output_path: 输出图片路径
    :return: 输出图片路径
    """

    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("需要安装 Pillow 库才能拼接图片: pip install Pillow")

    # 打开两张图片
    img1 = Image.open(img1_path)
    img2 = Image.open(img2_path)

    # 确保两张图片都是 RGB 模式（处理透明通道）
    if img1.mode != 'RGB':
        img1 = img1.convert('RGB')
    if img2.mode != 'RGB':
        img2 = img2.convert('RGB')

    # 获取图片尺寸
    w1, h1 = img1.size
    w2, h2 = img2.size

    # 计算拼接后的尺寸（宽度取较大值，高度为两者之和）
    new_width = max(w1, w2)
    new_height = h1 + h2

    # 创建新图片（白色背景）
    merged_img = Image.new('RGB', (new_width, new_height), (255, 255, 255))

    # 将两张图片粘贴到新图片上
    # img1 在上方（从 (0, 0) 开始）
    merged_img.paste(img1, (0, 0))
    # img2 在下方（从 (0, h1) 开始）
    merged_img.paste(img2, (0, h1))

    # 保存拼接后的图片
    merged_img.save(output_path, quality=95)
    print(f"图片拼接完成: {img1_path} + {img2_path} -> {output_path}")

    return output_path


def find_and_merge_paired_images(sorted_files):
    """
    检测并处理配对/多组图片（如 page01_01、page01_01(1)、page01_01(2)）
    合并后覆盖基础文件路径，并删除带括号的图片
    :param sorted_files: 排序后的文件列表
    :return: 处理后的文件列表（配对文件会被合并，单独文件保留）
    """
    # 创建文件名到文件信息的映射
    filename_map = {f['filename']: f for f in sorted_files}
    processed_files = []
    processed_names = set()

    for file_info in sorted_files:
        filename = file_info['filename']

        # 如果已经处理过，跳过
        if filename in processed_names:
            continue

        # 第一步：判断当前文件是否是基础文件（无 (数字) 后缀）
        base_match = re.match(r'^(.+)\.(jpg|jpeg|png)$', filename, re.IGNORECASE)
        if not base_match:
            # 非图片文件/不符合命名规则，直接保留
            processed_files.append(file_info)
            processed_names.add(filename)
            continue

        base_name = base_match.group(1)
        ext = base_match.group(2)

        # 第二步：收集同一基础名称下的所有后缀文件（(1)、(2)、(3)...）
        related_files = [file_info]  # 先加入基础文件
        suffix_num = 1
        while True:
            suffix_filename = f"{base_name}({suffix_num}).{ext}"
            if suffix_filename in filename_map:
                related_files.append(filename_map[suffix_filename])
                suffix_num += 1
            else:
                break

        # 如果只有基础文件，无后缀文件，直接保留
        if len(related_files) == 1:
            processed_files.append(file_info)
            processed_names.add(filename)
            continue

        # 第三步：依次合并所有相关文件（基础文件→(1)→(2)→...）
        print(f"检测到多组图片待合并: {[f['filename'] for f in related_files]}")
        # 初始化合并路径：先使用临时文件，最后覆盖基础文件
        temp_merged_path = None
        base_file_path = related_files[0]['full_path']  # 基础文件路径（最终要覆盖的）
        try:
            for i in range(len(related_files) - 1):
                # 拼接的两个文件：前一个合并结果（或基础文件） + 下一个后缀文件
                img1_path = related_files[i]['full_path'] if i == 0 else temp_merged_path
                img2_path = related_files[i + 1]['full_path']

                # 生成临时合并路径（最后一次合并直接覆盖基础文件）
                if i == len(related_files) - 2:
                    # 最后一次合并：直接覆盖基础文件
                    current_merged_path = base_file_path
                else:
                    # 中间合并：生成临时路径
                    temp_fd, temp_path = tempfile.mkstemp(suffix=f".{ext}", prefix=f"{base_name}_temp_")
                    os.close(temp_fd)
                    current_merged_path = temp_path

                # 执行垂直合并
                merge_images_vertically(img1_path, img2_path, current_merged_path)
                temp_merged_path = current_merged_path

            # 第四步：删除所有带括号的后缀文件
            for f in related_files[1:]:  # 跳过基础文件，删除(1)/(2)...文件
                suffix_file_path = f['full_path']
                if os.path.exists(suffix_file_path):
                    os.remove(suffix_file_path)
                    print(f"已删除后缀文件: {suffix_file_path}")

            # 合并完成，添加到处理列表（使用基础文件的信息，路径为覆盖后的路径）
            processed_files.append({
                'filename': related_files[0]['filename'],  # 沿用基础文件名
                'full_path': base_file_path,              # 覆盖后的基础文件路径
                'file_number': related_files[0].get('file_number', 0),
                'page_number': related_files[0].get('page_number', 0),
                'question_number': related_files[0].get('question_number', 0),
                'is_merged': True,
                'merged_from': [f['filename'] for f in related_files]
            })

            # 标记所有参与合并的文件为已处理
            for f in related_files:
                processed_names.add(f['filename'])

        except Exception as e:
            print(f"拼接多组图片失败 {[f['filename'] for f in related_files]}: {e}")
            # 合并失败，清理临时文件，逐个保留原文件
            if temp_merged_path and os.path.exists(temp_merged_path) and temp_merged_path != base_file_path:
                os.remove(temp_merged_path)
                print(f"已清理临时文件: {temp_merged_path}")
            # 合并失败，不删除任何文件，逐个保留原文件
            for f in related_files:
                processed_files.append(f)
                processed_names.add(f['filename'])

    # 按 file_number 重新排序
    processed_files.sort(key=lambda x: x.get('file_number', 0))

    return processed_files

# 修复：增加subject/grade/file_type/file_nom参数
def get_oss_image_url(file_path, bucket, subject, grade, file_type, file_nom, expire_time):
    """
    上传图片到OSS并生成带签名的URL
    :param file_path: 本地图片路径
    :param bucket: OSS Bucket实例
    :param subject: 学科
    :param grade: 年级
    :param file_type: 文件类型
    :param file_nom: 文件命名标识
    :param expire_time: URL过期时间（秒）
    :return: OSS URL
    """
    try:
        # 生成OSS存储的文件名（避免重复）
        file_name = f"{config['prefix']}/{subject}/{grade}/{file_type}/{file_nom}/{os.path.basename(file_path)}"
        # 上传文件到OSS
        bucket.put_object_from_file(file_name, file_path)
        # 生成带签名的临时URL

        url = bucket.sign_url('GET', file_name, expire_time)
        return url
        #调用URL时再启用
    except Exception as e:
        print(f"OSS上传/URL生成失败 {file_path}: {e}")
        #return "URL生成失败"

def main(args):
    root_folder = args.root_folder
    image_suffix = tuple(args.image_suffix)
    output_excel = args.url_excel
    sleep_time = args.sleep_time
    oss_expire_time = args.oss_expire_time

    required_oss_config = ("access_key_id", "access_key_secret", "endpoint", "bucket_name")
    missing_config = [key for key in required_oss_config if not config[key]]
    if missing_config:
        raise ValueError(f"缺少 OSS 配置: {', '.join(missing_config)}")

    auth = oss2.Auth(config["access_key_id"], config["access_key_secret"])
    bucket = oss2.Bucket(auth, config["endpoint"], config["bucket_name"])

    # 初始化存储结果的列表
    data_list = []

    for root, dirs, files in os.walk(root_folder):
        if os.path.basename(root) == "image_cut":
            # 拆分路径，提取【学科】【年级】【文件类型】
            path_split = root.split(os.sep)
            subs=path_split[-5]
            if subs[:2] in ['语文','英语','化学','物理']:
                subject=subs[:2] if len(path_split)>=5 else "未知学科"
                grade = path_split[-4] if len(path_split)>=4 else "未知年级"
                ft=path_split[-3]
                file_type = ft[:2] if len(path_split)>=3 else "未知类型"
                file_nom = path_split[-2] if len(path_split)>=2 else " "
            else:
                subs=path_split[-4]
                subject = subs[:2] if len(path_split)>=4 else "未知学科"
                grade = path_split[-3] if len(path_split)>=3 else "未知年级"
                ft=path_split[-2]
                file_type = ft[:3] if len(path_split)>=2 else "未知类型"
                file_nom="-"

            # 修正：补充文件完整路径到sorted_files
            sorted_files = []
            for file in files:
                if file.lower().endswith(image_suffix):
                    full_path = os.path.join(root, file)
                    # 调用排序函数并补充完整路径
                    file_info = get_sorted_image_files_by_number([file])[0] if get_sorted_image_files_by_number([file]) else {}
                    file_info.update({
                        "filename": file,
                        "full_path": full_path
                    })
                    sorted_files.append(file_info)

            print(f"找到 {len(sorted_files)} 个图片文件")

            # 检测并处理配对图片
            processed_files = find_and_merge_paired_images(sorted_files)
            print(f"处理后共 {len(processed_files)} 个文件（包含拼接后的图片）")

            # 遍历处理后的文件列表
            # ========== 修复后的代码片段（image_folder_url.py） ==========
            # 遍历处理后的文件列表 → 新增过滤条件
            for file_info in processed_files:
    # 过滤条件：
    # 1. 仅处理「未被合并的单独文件」或「合并后的基础文件」（排除被删除的后缀文件）
    # 2. 先检查文件是否真实存在（避免路径无效）
                if (file_info.get('is_merged', False) or os.path.exists(file_info['full_path'])):
                    img_full_path = file_info['full_path']
                    file_name = f"{config['prefix']}/{subject}/{grade}/{file_type}/{file_nom}/{file_info['filename']}"
                    file_name_use = f"{subject}/{grade}/{file_type}/{file_nom}/{file_info['filename']}"
                    if img_full_path.lower().endswith(image_suffix):
                        try:
                            img_url = get_oss_image_url(
                                img_full_path,
                                bucket,
                                subject,
                                grade,
                                file_type,
                                file_nom,
                                oss_expire_time
                            )
                            time.sleep(sleep_time)
                        #需要调用API时启用

                        except Exception as e:
                            print(f"URL生成失败 {img_full_path}: {e}")
                            img_url = "URL生成失败"
                            #需要调用API时启用
                            continue
                        data_list.append({
                            "学科": subject,
                            "年级": grade,
                            "文件类型": file_type,
                            "文件名称":file_nom,
                            "图片名称": file_name_use,#可以把文件夹名字删了
                            "图片完整路径": img_full_path,
                            "图片URL": img_url,
                            #需要调用API时启用
                        })
                        #print(f"✅ 处理完成: {img_full_path}")

    # 导出Excel
    df = pd.DataFrame(data_list)
    df.to_excel(output_excel, index=False, engine="openpyxl")

    print("="*50)
    print(f"✅ 全部处理完成！总计处理 {len(data_list)} 张图片")
    print(f"✅ 结果已保存至: {os.path.abspath(output_excel)}")

if __name__ == "__main__":
    ### Input arguments
    parser = argparse.ArgumentParser()

    parser.add_argument("-rf", "--root_folder", type=str, required=True, help="图片根文件夹路径")
    parser.add_argument("-is", "--image_suffix", type=str, nargs="+", default=[".png", ".jpg", ".jpeg"], help="处理的图片格式后缀")
    parser.add_argument("-ue", "--url_excel", type=str, required=True, help="生成的Excel保存路径")
    parser.add_argument("-st", "--sleep_time", type=float, default=0.5, help="每次请求休眠时间（秒）")
    parser.add_argument("-ot", "--oss_expire_time", type=int, default=3600 * 24 * 365, help="OSS URL过期时间（秒）")
    args = parser.parse_args()

    ### main process
    main(args)

    print("Done!")
