#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"

PYTHON_BIN="${PYTHON_BIN:-python3}"
DATA_ROOT="${DATA_ROOT:-.}"
SLEEP_TIME="${SLEEP_TIME:-0.5}"
MAX_POLL_DURATION="${MAX_POLL_DURATION:-1440}"
POLL_INTERVAL="${POLL_INTERVAL:-60}"
MAX_RETRIES="${MAX_RETRIES:-1}"

: "${JUDGE_URL:?请设置 JUDGE_URL}"
: "${RESULT_BASE_URL:?请设置 RESULT_BASE_URL}"
: "${BEARER_TOKEN:?请设置 BEARER_TOKEN}"

SUBJECTS=("CH" "CN" "EN" "PH")
if (( $# > 0 )); then
    SUBJECTS=("$@")
fi

for SUBJECT in "${SUBJECTS[@]}"; do
    case "$SUBJECT" in
        CH|CN|EN|PH) ;;
        *) echo "未知学科代码: $SUBJECT" >&2; exit 2 ;;
    esac

    SUBJECT_DIR="${DATA_ROOT}/${SUBJECT}"
    URL_EXCEL="${SUBJECT_DIR}/${SUBJECT}_base.xlsx"
    GT_EXCEL="${SUBJECT_DIR}/answer_${SUBJECT}.xlsx"
    TASK_EXCEL="${SUBJECT_DIR}/data/taskid_${SUBJECT}.xlsx"
    FETCH_EXCEL="${SUBJECT_DIR}/data/vis_result_${SUBJECT}.xlsx"
    RAW_RESULT="${SUBJECT_DIR}/data/task_result_${SUBJECT}.txt"
    FAILED_JSON="${SUBJECT_DIR}/data/failed_imgs_${SUBJECT}.json"
    MERGED_EXCEL="${SUBJECT_DIR}/result_${SUBJECT}.xlsx"
    FINAL_EXCEL="${SUBJECT_DIR}/final_result_${SUBJECT}.xlsx"
    ACCURACY_EXCEL="${SUBJECT_DIR}/accuracy_result_${SUBJECT}.xlsx"

    if [[ ! -f "$URL_EXCEL" || ! -f "$GT_EXCEL" ]]; then
        echo "缺少 ${SUBJECT} 的输入 Excel，请参考 README.md。" >&2
        exit 2
    fi
    mkdir -p -- "${SUBJECT_DIR}/data"

    retry_count=0
    while true; do
        submit_status=0
        "$PYTHON_BIN" ./02_get_taskid.py \
            -te "$TASK_EXCEL" -ue "$URL_EXCEL" -st "$SLEEP_TIME" || submit_status=$?

        fetch_status=0
        "$PYTHON_BIN" ./03_folder_answer_fetch.py \
            -t "$TASK_EXCEL" -o "$FETCH_EXCEL" -rp "$RAW_RESULT" \
            -to "$MAX_POLL_DURATION" -int "$POLL_INTERVAL" \
            -fo "$FAILED_JSON" || fetch_status=$?

        if (( submit_status == 0 && fetch_status == 0 )); then
            break
        fi
        if (( retry_count >= MAX_RETRIES )) || [[ ! -s "$FAILED_JSON" ]]; then
            echo "${SUBJECT} 处理失败，已停止后续统计。" >&2
            exit 1
        fi

        retry_count=$((retry_count + 1))
        "$PYTHON_BIN" ./02_get_taskid.py -ue "$URL_EXCEL" -cc "$FAILED_JSON"
    done

    "$PYTHON_BIN" ./04_merge_excel.py -gp "$GT_EXCEL" -vp "$FETCH_EXCEL" -op "$MERGED_EXCEL"
    "$PYTHON_BIN" ./05_answer_compare.py -ip "$MERGED_EXCEL" -op "$FINAL_EXCEL"
    "$PYTHON_BIN" ./06_calculate_accuracy.py -ip "$FINAL_EXCEL" -op "$ACCURACY_EXCEL" -sn "$SUBJECT"
done
