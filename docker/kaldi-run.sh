#!/bin/bash
# Kaldi-GOP 运行脚本
# 用于在 Docker 容器中执行 kaldi-dnn-ali-gop

set -e

AUDIO_DIR=$1
DATA_DIR=$2
RESULT_DIR=$3

# 检查参数
if [ -z "$AUDIO_DIR" ] || [ -z "$DATA_DIR" ] || [ -z "$RESULT_DIR" ]; then
    echo "用法: $0 <audio_dir> <data_dir> <result_dir>"
    exit 1
fi

echo "=== Kaldi-GOP 评分开始 ==="
echo "音频目录: $AUDIO_DIR"
echo "数据目录: $DATA_DIR"
echo "结果目录: $RESULT_DIR"

# 设置 Kaldi 环境
export KALDI_ROOT=${KALDI_ROOT:-/opt/kaldi}
export PATH=$KALDI_ROOT/src/bin:$KALDI_ROOT/tools/openfst/bin:$PATH

# 进入 kaldi-gop 目录
cd /app/kaldi-gop

# 准备数据目录结构
mkdir -p "$DATA_DIR"

# 运行 kaldi-dnn-ali-gop 的 run.sh
# NOTE: 实际命令取决于 kaldi-dnn-ali-gop 的具体实现
# 通常需要：
# 1. 准备 wav.scp, text, utt2spk 等文件
# 2. 提取 MFCC 特征
# 3. 运行强制对齐
# 4. 计算 GOP 分数

# 创建 Kaldi 格式的输入文件
echo "=== 准备 Kaldi 输入 ==="

# wav.scp: <utt_id> <wav_path>
find "$AUDIO_DIR" -name "*.wav" | while read wav; do
    utt_id=$(basename "$wav" .wav)
    speaker=$(basename $(dirname "$wav"))
    echo "${speaker}_${utt_id} $wav"
done > "$DATA_DIR/wav.scp"

# text: <utt_id> <transcript>
find "$AUDIO_DIR" -name "*.lab" | while read lab; do
    utt_id=$(basename "$lab" .lab)
    speaker=$(basename $(dirname "$lab"))
    transcript=$(cat "$lab")
    echo "${speaker}_${utt_id} $transcript"
done > "$DATA_DIR/text"

# utt2spk: <utt_id> <speaker_id>
find "$AUDIO_DIR" -name "*.wav" | while read wav; do
    utt_id=$(basename "$wav" .wav)
    speaker=$(basename $(dirname "$wav"))
    echo "${speaker}_${utt_id} $speaker"
done > "$DATA_DIR/utt2spk"

# spk2utt
utils/utt2spk_to_spk2utt.pl "$DATA_DIR/utt2spk" > "$DATA_DIR/spk2utt"

echo "=== 运行 GOP 评分 ==="

# 检查是否有预训练模型
MODEL_DIR=/app/models/librispeech
if [ ! -d "$MODEL_DIR" ]; then
    echo "警告: 预训练模型不存在，将使用示例模型"
    MODEL_DIR=/app/kaldi-gop/exp/models
fi

# 提取 MFCC 特征
steps/make_mfcc.sh --nj 1 "$DATA_DIR" "$DATA_DIR/log" "$DATA_DIR/mfcc" || true

# 计算 CMVN
steps/compute_cmvn_stats.sh "$DATA_DIR" "$DATA_DIR/log" "$DATA_DIR/mfcc" || true

# 运行强制对齐和 GOP 计算
# 这里使用 kaldi-dnn-ali-gop 的脚本
if [ -f "local/gop.sh" ]; then
    local/gop.sh "$DATA_DIR" "$MODEL_DIR" "$RESULT_DIR"
else
    echo "警告: gop.sh 不存在，尝试使用默认流程"
    
    # 强制对齐
    steps/align_si.sh --nj 1 "$DATA_DIR" data/lang "$MODEL_DIR" "$RESULT_DIR/ali" || true
    
    # 计算 GOP
    local/compute_gop.sh "$DATA_DIR" "$MODEL_DIR" "$RESULT_DIR/ali" "$RESULT_DIR" || true
fi

echo "=== 生成 TextGrid ==="

# 将对齐结果转换为 TextGrid 格式
mkdir -p "$RESULT_DIR/aligned_textgrid"

# 使用 Python 脚本转换（如果存在）
if [ -f "local/ali_to_textgrid.py" ]; then
    python3 local/ali_to_textgrid.py \
        --ali-dir "$RESULT_DIR/ali" \
        --output-dir "$RESULT_DIR/aligned_textgrid"
fi

# 整理 GOP 输出
if [ -f "$RESULT_DIR/gop.1.ark" ]; then
    # Kaldi ark 格式转文本
    copy-vector ark:"$RESULT_DIR/gop.1.ark" ark,t:"$RESULT_DIR/gop.txt" 2>/dev/null || true
fi

echo "=== Kaldi-GOP 评分完成 ==="
echo "结果保存在: $RESULT_DIR"

# 列出输出文件
ls -la "$RESULT_DIR"
