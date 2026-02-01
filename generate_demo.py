
import sys
from pathlib import Path
from datetime import datetime
from jinja2 import Environment, FileSystemLoader

# 添加项目根目录到 sys.path
sys.path.append(str(Path(__file__).parent.parent))

from src.report.render_html import TEMPLATES_DIR, get_phoneme_tips

def generate_demo_report():
    output_path = Path("data/out/demo/demo_report.html")
    
    # 1. 构造模拟数据
    # 文本: "Climate change is a long-term shift in global or regional climate patterns. Often climate change refers specifically to the rise in global temperatures."
    
    alignment_words = [
        {"word": "Climate", "score": 95, "tag": "ok", "start": 0.0, "end": 0.5, "stress": 0.9},
        {"word": "change", "score": 90, "tag": "ok", "start": 0.5, "end": 1.0, "stress": 0.8, 
         "pause": {"type": "good", "duration": "0.8s"}}, # Good Pause (Green H)
        {"word": "is", "score": 90, "tag": "ok", "start": 1.0, "end": 1.2, "stress": 0.3},
        {"word": "a", "score": 85, "tag": "ok", "start": 1.2, "end": 1.3, "stress": 0.2},
        {"word": "long-term", "score": 92, "tag": "ok", "start": 1.3, "end": 2.0, "stress": 0.8},
        {"word": "shift", "score": 45, "tag": "poor", "start": 2.1, "end": 2.5, "stress": 0.9,
         "pause": {"type": "bad", "duration": "1.2s"}}, # Bad Pause (Red H)
        {"word": "in", "score": 88, "tag": "ok", "start": 2.5, "end": 2.7, "stress": 0.2},
        {"word": "global", "score": 96, "tag": "ok", "start": 2.7, "end": 3.2, "stress": 0.7},
        {"word": "or", "score": 70, "tag": "weak", "start": 3.2, "end": 3.4, "stress": 0.4,
         "pause": {"type": "optional", "duration": "0.3s"}}, # Optional (Gray H)
        {"word": "regional", "score": 95, "tag": "ok", "start": 3.4, "end": 4.0, "stress": 0.8},
        {"word": "climate", "score": 94, "tag": "ok", "start": 4.0, "end": 4.5, "stress": 0.9},
        {"word": "patterns", "score": 98, "tag": "ok", "start": 4.5, "end": 5.1, "stress": 0.8},
        {"word": ".", "score": 0, "tag": "ok", "start": 5.1, "end": 5.1, "stress": 0.0,
         "pause": {"type": "good", "duration": "1.5s"}}, # Good Pause at period
        
        {"word": "Often", "score": 92, "tag": "ok", "start": 5.5, "end": 6.0, "stress": 0.7},
        {"word": "climate", "score": 60, "tag": "weak", "start": 6.0, "end": 6.5, "stress": 0.8},
        {"word": "change", "score": 90, "tag": "ok", "start": 6.5, "end": 7.0, "stress": 0.8,
         "pause": {"type": "missed"}}, # Missed Pause (Red I-Bar)
        {"word": "refers", "score": 40, "tag": "poor", "start": 7.0, "end": 7.5, "stress": 0.9},
        {"word": "specifically", "score": 85, "tag": "ok", "start": 7.5, "end": 8.5, "stress": 0.6},
        {"word": "to", "score": 90, "tag": "ok", "start": 8.5, "end": 8.7, "stress": 0.2},
        {"word": "the", "score": 0, "tag": "missing", "start": 8.7, "end": 8.7, "stress": 0.1},
        {"word": "rise", "score": 95, "tag": "ok", "start": 8.8, "end": 9.2, "stress": 0.8},
        {"word": "in", "score": 90, "tag": "ok", "start": 9.2, "end": 9.4, "stress": 0.2},
        {"word": "global", "score": 96, "tag": "ok", "start": 9.4, "end": 9.9, "stress": 0.7},
        {"word": "temperatures", "score": 98, "tag": "ok", "start": 9.9, "end": 10.8, "stress": 0.9},
    ]

    # 颜色配置 (Mock config)
    colors = {
        "ok": "#4CAF50",
        "weak": "#FFC107",
        "missing": "#F44336",
        "poor": "#E91E63",
    }

    # 构造完整数据字典
    data = {
        "meta": {
            "task_id": "demo-case-001",
            "student_id": "advanced_learner",
            "student_name": "Demo User (Real Case)",
            "submission_id": "sub_demo_2026",
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "engine_used": "kaldi-gop-v2",
        },
        "scores": {
            "overall_100": 78.5,
            "pronunciation_100": 72.0,
            "fluency_100": 85.0,
            "intonation_100": 80.0,
            "completeness_100": 90.0,
        },
        "alignment": {
            "words": alignment_words
        },
        "analysis": {
            "weak_words": ["change", "or", "climate"],
            "weak_phonemes": ["/tʃ/", "/ɔː/", "/m/"],
            "missing_words": ["a", "the"],
        },
        "feedback": {
            "cn_summary": "整体朗读流畅度不错，但存在部分连词漏读现象。几个核心名词的发音需要更饱满。",
            "cn_actions": [
                "注意虚词 'a' 和 'the' 不要吞音。",
                "练习 /tʃ/ (change) 的发音，确保气流冲破阻碍。",
                "单词 'refers' 的重音位置需要纠正。"
            ],
            "practice": ["climate change", "refers to", "global shift"]
        },
        "colors": colors,
        "audio_base64": None, # PDF Mode
        "phoneme_tips": [], 
        "pronunciation_analysis": [
            {
                "target": "/n/",
                "name": "鼻音 (Nasal)",
                "advice": "💡 技巧：发 /n/ 音时，舌尖要紧贴上齿龈（门牙后面），让气流从鼻子里出来。摸摸鼻子，会有震动的感觉哦！",
                "mistakes": [
                    {
                        "type": "substitution",
                        "actual": "/ŋ/",
                        "desc": "发音位置靠后了",
                        "words": [
                            {"text": "in", "ipa": "/ɪ<span class='err'>ŋ</span>/"},
                            {"text": "patterns", "ipa": "/'pætər<span class='err'>ŋ</span>z/"}
                        ]
                    },
                    {
                        "type": "omission",
                        "actual": "(没读)",
                        "desc": "漏读了这个音",
                        "words": [
                            {"text": "regional", "ipa": "/'riːdʒə<span class='err'>_</span>əl/"}
                        ]
                    }
                ]
            },
            {
                "target": "/t/",
                "name": "清辅音 (Plosive)",
                "advice": "💡 技巧：这是个“爆破音”。舌尖先抵住上齿龈憋住气，然后突然松开，让气流冲出来。声带不要震动。",
                "mistakes": [
                    {
                        "type": "substitution",
                        "actual": "/d/",
                        "desc": "读成了浊音 /d/",
                        "words": [
                            {"text": "temperature", "ipa": "/'temprə<span class='err'>d</span>ʃər/"},
                            {"text": "shift", "ipa": "/ʃɪf<span class='err'>d</span>/"}
                        ]
                    }
                ]
            },
            {
                "target": "/θ/",
                "name": "咬舌音 (Dental)",
                "advice": "💡 技巧：这是著名的“咬舌音”。一定要把舌尖轻轻伸到上下牙齿之间，向外吹气。千万不要缩在里面读成 /s/。",
                "mistakes": [
                    {
                        "type": "substitution",
                        "actual": "/s/",
                        "desc": "没有伸舌头 (读成了 /s/)",
                        "words": [
                            {"text": "specifically", "ipa": "/spə'sɪfɪkli/"} 
                        ]
                    }
                ]
            }
        ],
        "pac_chart_data": [
            {"x": 0, "y": 98},
            {"x": 2, "y": 105},
            {"x": 4, "y": 140},  # Peak
            {"x": 6, "y": 120},
            {"x": 8, "y": 95},   # Slow down
            {"x": 10, "y": 110},
        ],
        "hesitations": {
            "score_label": "Natural",
            "desc": "你的表达很自然，只有少量的犹豫。保持自信！💪",
            "fillers": [
                {"word": "uh", "count": 4},
                {"word": "um", "count": 2},
                {"word": "you know", "count": 1}
            ],
            "examples": [
                {
                    "original": "He was, <span class='filler'>uh</span>, prime minister and he was, <span class='filler'>uh</span>, Danish weather.",
                    "corrected": "He was prime minister and he was Danish weather."
                }
            ],
            "tips": [
                "试着在想词的时候停顿一下，而不是说 'uh'。",
                "放慢语速可以有效减少不必要的填充词。"
            ]
        },
        "completeness_analysis": {
            "title": "Completeness (完整度)",
            "score_label": "High",
            "coverage": 90, # 90% coverage
            "missing_stats": {
                "total": 3,
                "keywords": 0,
                "function_words": 3
            },
            "insight": "表现出色！你几乎读完了所有内容。漏读的仅仅是几个无关紧要的功能词（如 'a', 'the'），这对理解影响不大。",
            "tips": [
                "注意连读时的吞音现象。",
                "功能词虽然不重读，但也不能完全省略哦。"
            ]
        },
        "audio_stem": "ZhangSan_Unit1_Lesson2", # 模拟音频文件名
    }

    # 2. 渲染模板
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("report.html.j2")
    html_content = template.render(**data)

    # 3. 保存
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_content, encoding="utf-8")
    print(f"✅ Demo 报告已生成: {output_path.absolute()}")

if __name__ == "__main__":
    generate_demo_report()
