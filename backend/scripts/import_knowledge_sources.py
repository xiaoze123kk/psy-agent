from __future__ import annotations

import argparse
import asyncio
import io
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.models import KnowledgeArticle, KnowledgeSource, utcnow
from app.db.session import SessionLocal, init_db
from app.services.deepseek_client import deepseek_client
from app.services.knowledge_service import SEED_SOURCES, _sync_article_chunks


ALLOWED_HOSTS = {
    "nimh_public_domain": {"www.nimh.nih.gov", "nimh.nih.gov"},
    "medlineplus_public_domain": {"medlineplus.gov", "www.medlineplus.gov"},
    "childmind_mhdb": {"matter.childmind.org", "github.com"},
    "internal_curated": set(),
}

SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "form"}
TEXT_TAGS = {"p", "li", "h1", "h2", "h3"}

MEDLINEPLUS_XML_INDEX_URL = "https://medlineplus.gov/xml.html"
MEDLINEPLUS_XML_BASE_URL = "https://medlineplus.gov/"
MEDLINEPLUS_MENTAL_GROUPS = {"Mental Health and Behavior"}
MEDLINEPLUS_SUBSTANCE_GROUPS = {"Substance Use and Disorders"}
MEDLINEPLUS_ADJACENT_TITLES = {
    "Alzheimer's Caregivers",
    "Benefits of Exercise",
    "Bullying and Cyberbullying",
    "Caregiver Health",
    "Caregivers",
    "Child Abuse",
    "Child Development",
    "Child Sexual Abuse",
    "College Health",
    "Disabilities",
    "Elder Abuse",
    "End of Life Issues",
    "Evaluating Health Information",
    "Exercise and Physical Fitness",
    "Exercise for Children",
    "Exercise for Older Adults",
    "Family Issues",
    "Health Literacy",
    "Health Risks of an Inactive Lifestyle",
    "Healthy Aging",
    "Healthy Living",
    "Healthy Sleep",
    "Homelessness and Health",
    "Insomnia",
    "Intimate Partner Violence",
    "Parenting",
    "School Health",
    "Sexual Assault",
    "Sleep Apnea",
    "Sleep Disorders",
    "Talking With Your Doctor",
    "Teen Health",
    "Teen Violence",
    "Traumatic Brain Injury",
    "Veterans and Military Family Health",
}

MEDLINEPLUS_HIGH_CONFIDENCE_GROUPS = {
    "Wellness and Lifestyle",
    "Social/Family Issues",
    "Older Adults",
    "Personal Health Issues",
    "Health System",
    "Safety Issues",
    "Fitness and Exercise",
    "Population Groups",
}

MEDLINEPLUS_HIGH_CONFIDENCE_TITLES = {
    "Advance Directives",
    "Assisted Living",
    "Back Pain",
    "Balance Problems",
    "Child Safety",
    "Chronic Pain",
    "Common Infant and Newborn Problems",
    "Concussion",
    "Disabilities",
    "End of Life Issues",
    "Fainting",
    "Falls",
    "Financial Assistance",
    "Health Checkup",
    "Health Literacy",
    "Health Occupations",
    "Health Screening",
    "Healthy Aging",
    "Healthy Living",
    "Home Care Services",
    "Hospice Care",
    "How Much Exercise Do I Need?",
    "Impaired Driving",
    "Medical Device Safety",
    "Medical Ethics",
    "Medicare",
    "Migraine",
    "Mobility Aids",
    "Nursing Homes",
    "Occupational Health",
    "Occupational Health for Health Care Providers",
    "Older Adult Health",
    "Palliative Care",
    "Pain",
    "Patient Rights",
    "Personal Health Records",
    "Restless Legs",
    "Rural Health Concerns",
    "Safety",
    "Sports Fitness",
    "Sports Safety",
    "Stuttering",
    "Telehealth",
    "Understanding Medical Research",
    "Veterans and Military Health",
    "Vital Signs",
    "Walking Problems",
    "Assistive Devices",
    "Autonomic Nervous System Disorders",
    "Carpal Tunnel Syndrome",
    "Complex Regional Pain Syndrome",
    "Degenerative Nerve Diseases",
    "Dystonia",
    "Headache",
    "Hearing Disorders and Deafness",
    "Hearing Problems in Children",
    "Lewy Body Dementia",
    "Movement Disorders",
    "Neuromuscular Disorders",
    "Parkinson's Disease",
    "Peripheral Nerve Disorders",
    "Sciatica",
    "Spinal Cord Diseases",
    "Stroke Rehabilitation",
    "Thoracic Outlet Syndrome",
    "Tourette Syndrome",
    "Tremor",
    "Trigeminal Neuralgia",
}

MEDLINEPLUS_HIGH_CONFIDENCE_KEYWORDS = (
    "abuse",
    "aging",
    "caregiver",
    "child",
    "college",
    "communication",
    "doctor",
    "exercise",
    "family",
    "fatigue",
    "fitness",
    "grief",
    "health literacy",
    "healthy",
    "help",
    "homeless",
    "living",
    "nutrition",
    "pain",
    "parent",
    "safety",
    "school",
    "sleep",
    "stress",
    "teen",
    "violence",
)

MEDLINEPLUS_GROUP_TAGS = {
    "Wellness and Lifestyle": ["生活方式", "自助", "健康习惯"],
    "Social/Family Issues": ["家庭", "社会支持", "关系"],
    "Children and Teenagers": ["儿童", "青少年", "学校"],
    "Older Adults": ["老年", "照护", "认知"],
    "Personal Health Issues": ["个人健康", "求助", "就医"],
    "Health System": ["医疗系统", "就医沟通", "资源"],
    "Safety Issues": ["安全", "风险", "预防"],
    "Fitness and Exercise": ["运动", "压力", "睡眠"],
    "Food and Nutrition": ["营养", "饮食", "生活方式"],
    "Population Groups": ["人群", "支持", "资源"],
}

MEDLINEPLUS_TITLE_TRANSLATIONS = {
    "Alzheimer's Disease": ("阿尔茨海默病", "cognitive"),
    "Antidepressants": ("抗抑郁药基础信息", "medication"),
    "Anxiety": ("焦虑", "emotion"),
    "Attention Deficit Hyperactivity Disorder": ("注意缺陷多动障碍", "teen"),
    "Autism Spectrum Disorder": ("自闭症谱系障碍", "teen"),
    "Bereavement": ("哀伤与丧亲", "emotion"),
    "Bipolar Disorder": ("双相障碍", "emotion"),
    "Cancer--Living with Cancer": ("癌症共处中的心理支持", "coping"),
    "Child Behavior Disorders": ("儿童行为问题", "teen"),
    "Child Mental Health": ("儿童心理健康", "teen"),
    "Compulsive Gambling": ("赌博成瘾", "behavior"),
    "Coping with Chronic Illness": ("慢性病共处与心理调适", "coping"),
    "Coping with Disasters": ("灾害后的心理应对", "coping"),
    "Delirium": ("谵妄", "cognitive"),
    "Dementia": ("痴呆", "cognitive"),
    "Depression": ("抑郁", "emotion"),
    "Developmental Disabilities": ("发育障碍", "teen"),
    "Dual Diagnosis": ("双重诊断", "substance"),
    "Eating Disorders": ("进食障碍", "emotion"),
    "How to Improve Mental Health": ("如何改善心理健康", "self_help"),
    "Learning Disabilities": ("学习障碍", "teen"),
    "Memory": ("记忆", "cognitive"),
    "Mental Disorders": ("精神障碍概览", "emotion"),
    "Mental Health": ("心理健康", "self_help"),
    "Mild Cognitive Impairment": ("轻度认知障碍", "cognitive"),
    "Mood Disorders": ("心境障碍", "emotion"),
    "Obsessive-Compulsive Disorder": ("强迫障碍", "emotion"),
    "Older Adult Mental Health": ("老年心理健康", "cognitive"),
    "Panic Disorder": ("惊恐障碍", "emotion"),
    "Personality Disorders": ("人格障碍", "emotion"),
    "Phobias": ("恐惧症", "emotion"),
    "Post-Traumatic Stress Disorder": ("创伤后应激障碍", "emotion"),
    "Postpartum Depression": ("产后抑郁", "emotion"),
    "Prader-Willi Syndrome": ("普拉德-威利综合征", "genetics"),
    "Psychotic Disorders": ("精神病性障碍", "emotion"),
    "Schizophrenia": ("精神分裂症", "emotion"),
    "Seasonal Affective Disorder": ("季节性情感障碍", "emotion"),
    "Self-Harm": ("自伤", "safety"),
    "Stress": ("压力", "emotion"),
    "Suicide": ("自杀风险", "safety"),
    "Teen Depression": ("青少年抑郁", "teen"),
    "Teen Development": ("青少年发展", "teen"),
    "Teen Mental Health": ("青少年心理健康", "teen"),
    "Alcohol": ("酒精与健康", "substance"),
    "Alcohol Use Disorder (AUD)": ("酒精使用障碍", "substance"),
    "Alcohol Use Disorder (AUD) Treatment": ("酒精使用障碍治疗", "substance"),
    "Anabolic Steroids": ("合成代谢类固醇滥用", "substance"),
    "Club Drugs": ("俱乐部药物", "substance"),
    "Cocaine": ("可卡因", "substance"),
    "Drug Use and Addiction": ("药物使用与成瘾", "substance"),
    "Drugs and Young People": ("青少年药物使用", "teen"),
    "E-Cigarettes": ("电子烟", "substance"),
    "Fetal Alcohol Spectrum Disorders": ("胎儿酒精谱系障碍", "substance"),
    "Heroin": ("海洛因", "substance"),
    "Inhalants": ("吸入剂滥用", "substance"),
    "Marijuana": ("大麻", "substance"),
    "Methamphetamine": ("甲基苯丙胺", "substance"),
    "Opioid Overdose": ("阿片类药物过量", "substance"),
    "Opioid Use Disorder (OUD) Treatment": ("阿片使用障碍治疗", "substance"),
    "Opioids and Opioid Use Disorder (OUD)": ("阿片类药物与阿片使用障碍", "substance"),
    "Pregnancy and Opioids": ("妊娠与阿片类药物", "substance"),
    "Pregnancy and Substance Use": ("妊娠与物质使用", "substance"),
    "Prescription Drug Misuse": ("处方药误用", "substance"),
    "Quitting Smoking": ("戒烟", "substance"),
    "Safe Opioid Use": ("安全使用阿片类药物", "substance"),
    "Smokeless Tobacco": ("无烟烟草", "substance"),
    "Smoking": ("吸烟", "substance"),
    "Smoking and Youth": ("青少年吸烟", "teen"),
    "Underage Drinking": ("未成年人饮酒", "teen"),
    "Alzheimer's Caregivers": ("阿尔茨海默病照护者支持", "relationship"),
    "Benefits of Exercise": ("运动对健康的益处", "self_help"),
    "Bullying and Cyberbullying": ("欺凌与网络欺凌", "teen"),
    "Caregiver Health": ("照护者健康", "relationship"),
    "Caregivers": ("照护者支持", "relationship"),
    "Child Abuse": ("儿童虐待", "safety"),
    "Child Development": ("儿童发展", "teen"),
    "Child Sexual Abuse": ("儿童性虐待", "safety"),
    "College Health": ("大学生健康", "teen"),
    "Disabilities": ("残障与社会支持", "relationship"),
    "Elder Abuse": ("老年虐待", "safety"),
    "End of Life Issues": ("生命末期议题", "coping"),
    "Evaluating Health Information": ("评估健康信息", "self_help"),
    "Exercise and Physical Fitness": ("运动与身体活动", "self_help"),
    "Exercise for Children": ("儿童运动", "teen"),
    "Exercise for Older Adults": ("老年人运动", "self_help"),
    "Family Issues": ("家庭议题", "relationship"),
    "Health Literacy": ("健康素养", "self_help"),
    "Health Risks of an Inactive Lifestyle": ("久坐生活方式风险", "self_help"),
    "Healthy Aging": ("健康老龄化", "self_help"),
    "Healthy Living": ("健康生活方式", "self_help"),
    "Healthy Sleep": ("健康睡眠", "sleep"),
    "Homelessness and Health": ("无家可归与健康", "safety"),
    "Insomnia": ("失眠", "sleep"),
    "Intimate Partner Violence": ("亲密伴侣暴力", "safety"),
    "Parenting": ("养育与亲子关系", "relationship"),
    "School Health": ("学校健康", "teen"),
    "Sexual Assault": ("性侵害", "safety"),
    "Sleep Apnea": ("睡眠呼吸暂停", "sleep"),
    "Sleep Disorders": ("睡眠障碍", "sleep"),
    "Talking With Your Doctor": ("如何和医生沟通", "self_help"),
    "Teen Health": ("青少年健康", "teen"),
    "Teen Violence": ("青少年暴力", "safety"),
    "Traumatic Brain Injury": ("创伤性脑损伤", "cognitive"),
    "Veterans and Military Family Health": ("退伍军人与军属健康", "coping"),
    "Back Pain": ("背痛", "coping"),
    "Chronic Pain": ("慢性疼痛", "coping"),
    "Headache": ("头痛", "coping"),
    "Migraine": ("偏头痛", "coping"),
    "Pain": ("疼痛", "coping"),
    "Restless Legs": ("不宁腿综合征", "sleep"),
    "Concussion": ("脑震荡", "cognitive"),
    "Stuttering": ("口吃", "coping"),
    "Speech and Language Problems in Children": ("儿童言语和语言问题", "teen"),
    "Tourette Syndrome": ("抽动秽语综合征", "teen"),
    "Walking Problems": ("行走困难", "coping"),
    "Falls": ("跌倒预防", "safety"),
    "Mobility Aids": ("行动辅助工具", "self_help"),
    "Palliative Care": ("姑息照护", "coping"),
    "Hospice Care": ("临终关怀", "coping"),
    "Patient Rights": ("患者权利", "self_help"),
    "Patient Safety": ("患者安全", "safety"),
    "Choosing a Doctor or Health Care Service": ("如何选择医生或医疗服务", "self_help"),
    "School Health": ("学校健康", "teen"),
    "College Health": ("大学生健康", "teen"),
    "Teen Health": ("青少年健康", "teen"),
    "Baby Health Checkup": ("婴儿健康检查", "teen"),
    "Toddler Health": ("幼儿健康", "teen"),
    "Toddler Development": ("幼儿发展", "teen"),
}

MEDLINEPLUS_EXTRA_TAGS = {
    "Anxiety": ["焦虑", "担心", "紧张", "panic"],
    "Depression": ["抑郁", "低落", "心境", "求助"],
    "Stress": ["压力", "应激", "调节", "自助"],
    "Panic Disorder": ["惊恐", "惊恐发作", "心慌", "呼吸"],
    "Obsessive-Compulsive Disorder": ["强迫", "反复确认", "侵入想法"],
    "Post-Traumatic Stress Disorder": ["创伤", "PTSD", "闪回", "应激"],
    "Self-Harm": ["自伤", "安全", "危机", "求助"],
    "Suicide": ["自杀", "危机", "988", "安全"],
    "Teen Depression": ["青少年", "抑郁", "学生", "求助"],
    "Teen Mental Health": ["青少年", "心理健康", "学校", "家庭"],
    "Eating Disorders": ["进食障碍", "饮食", "身体形象"],
    "Bereavement": ["哀伤", "丧失", "悲伤"],
    "Mental Health": ["心理健康", "自助", "求助"],
    "How to Improve Mental Health": ["心理健康", "自助", "运动", "睡眠"],
    "Alcohol": ["酒精", "饮酒", "喝酒", "成瘾"],
    "Alcohol Use Disorder (AUD)": ["酒精成瘾", "酒精依赖", "酗酒", "戒酒", "成瘾"],
    "Alcohol Use Disorder (AUD) Treatment": ["酒精成瘾", "戒酒", "治疗", "酒精依赖"],
    "Drug Use and Addiction": ["药物成瘾", "成瘾", "物质使用", "药物滥用"],
    "Drugs and Young People": ["青少年", "药物", "成瘾", "物质使用"],
    "Opioids and Opioid Use Disorder (OUD)": ["阿片", "成瘾", "药物依赖", "物质使用"],
    "Opioid Overdose": ["阿片", "过量", "急救", "安全"],
    "Opioid Use Disorder (OUD) Treatment": ["阿片", "成瘾", "治疗", "戒断"],
    "Prescription Drug Misuse": ["处方药", "误用", "成瘾", "药物滥用"],
    "Quitting Smoking": ["戒烟", "烟草", "尼古丁", "成瘾"],
    "Smoking": ["吸烟", "烟草", "尼古丁", "成瘾"],
    "E-Cigarettes": ["电子烟", "尼古丁", "青少年", "成瘾"],
    "Marijuana": ["大麻", "成瘾", "物质使用"],
    "Cocaine": ["可卡因", "成瘾", "毒品"],
    "Heroin": ["海洛因", "阿片", "成瘾"],
    "Methamphetamine": ["冰毒", "甲基苯丙胺", "成瘾"],
    "Underage Drinking": ["未成年人饮酒", "青少年", "酒精", "成瘾"],
    "Alzheimer's Caregivers": ["照护者", "阿尔茨海默", "照护压力", "家庭"],
    "Benefits of Exercise": ["运动", "情绪", "压力", "自助"],
    "Bullying and Cyberbullying": ["欺凌", "网络欺凌", "青少年", "学校"],
    "Caregiver Health": ["照护者", "照护压力", "家庭", "支持"],
    "Caregivers": ["照护者", "家庭", "支持", "照护压力"],
    "Child Abuse": ["儿童虐待", "安全", "求助", "创伤"],
    "Child Development": ["儿童发展", "亲子", "成长", "青少年"],
    "Child Sexual Abuse": ["儿童性虐待", "安全", "创伤", "求助"],
    "College Health": ["大学生", "压力", "睡眠", "健康"],
    "Disabilities": ["残障", "支持", "适应", "家庭"],
    "Elder Abuse": ["老年虐待", "安全", "照护", "求助"],
    "End of Life Issues": ["临终", "哀伤", "家庭", "照护"],
    "Evaluating Health Information": ["健康信息", "辨别", "信息素养"],
    "Exercise and Physical Fitness": ["运动", "情绪", "压力", "睡眠"],
    "Exercise for Children": ["儿童运动", "青少年", "运动", "健康"],
    "Exercise for Older Adults": ["老年人", "运动", "情绪", "健康"],
    "Family Issues": ["家庭", "关系", "沟通", "冲突"],
    "Health Literacy": ["健康素养", "信息", "沟通", "就医"],
    "Health Risks of an Inactive Lifestyle": ["久坐", "运动", "生活方式", "情绪"],
    "Healthy Aging": ["老年", "健康", "认知", "生活方式"],
    "Healthy Living": ["健康生活", "睡眠", "运动", "压力"],
    "Healthy Sleep": ["睡眠", "健康睡眠", "作息", "失眠"],
    "Homelessness and Health": ["无家可归", "安全", "资源", "支持"],
    "Insomnia": ["失眠", "睡不着", "睡眠", "焦虑"],
    "Intimate Partner Violence": ["亲密伴侣暴力", "家暴", "安全", "关系"],
    "Parenting": ["养育", "亲子", "家庭", "沟通"],
    "School Health": ["学校", "学生", "青少年", "健康"],
    "Sexual Assault": ["性侵害", "创伤", "安全", "求助"],
    "Sleep Apnea": ["睡眠呼吸暂停", "睡眠", "打鼾", "疲劳"],
    "Sleep Disorders": ["睡眠障碍", "失眠", "睡眠", "作息"],
    "Talking With Your Doctor": ["就医沟通", "医生", "求助", "表达"],
    "Teen Health": ["青少年", "学生", "健康", "成长"],
    "Teen Violence": ["青少年暴力", "安全", "学校", "冲突"],
    "Traumatic Brain Injury": ["脑损伤", "认知", "创伤", "康复"],
    "Veterans and Military Family Health": ["军属", "退伍军人", "创伤", "家庭"],
    "Back Pain": ["背痛", "疼痛", "慢性疼痛", "压力", "睡眠"],
    "Chronic Pain": ["慢性疼痛", "疼痛", "情绪", "压力", "睡眠"],
    "Headache": ["头痛", "疼痛", "压力", "睡眠", "烦躁"],
    "Migraine": ["偏头痛", "头痛", "疼痛", "压力", "睡眠"],
    "Pain": ["疼痛", "慢性疼痛", "情绪", "压力", "睡眠"],
    "Restless Legs": ["不宁腿", "睡眠", "失眠", "腿部不适"],
    "Concussion": ["脑震荡", "认知", "头痛", "恢复", "创伤"],
    "Stuttering": ["口吃", "沟通", "社交压力", "儿童"],
    "Speech and Language Problems in Children": ["儿童语言", "沟通", "学校", "发育"],
    "Tourette Syndrome": ["抽动", "青少年", "学校", "社交"],
    "Walking Problems": ["行走困难", "行动能力", "康复", "支持"],
    "Falls": ["跌倒", "老年", "安全", "预防"],
    "Mobility Aids": ["行动辅助", "残障", "独立生活", "支持"],
    "Palliative Care": ["姑息照护", "慢病", "疼痛", "家庭", "照护"],
    "Hospice Care": ["临终关怀", "家庭", "哀伤", "照护"],
    "Patient Rights": ["患者权利", "就医沟通", "知情同意", "求助"],
    "Patient Safety": ["患者安全", "就医", "风险", "沟通"],
    "Choosing a Doctor or Health Care Service": ["选择医生", "就医沟通", "求助", "医疗服务"],
    "School Health": ["学校压力", "学生", "青少年", "学校健康"],
    "College Health": ["大学生压力", "大学生", "睡眠", "心理健康"],
    "Teen Health": ["青少年压力", "学生", "学校", "成长"],
    "Baby Health Checkup": ["婴儿健康检查", "家长", "儿童健康"],
    "Toddler Health": ["幼儿健康", "家长", "儿童发展"],
    "Toddler Development": ["幼儿发展", "家长", "儿童发展"],
}

NIMH_PUBLICATIONS_URL = "https://www.nimh.nih.gov/health/publications"
NIMH_TOPICS_URL = "https://www.nimh.nih.gov/health/topics"
NIMH_BASE_URL = "https://www.nimh.nih.gov"
NIMH_EXCLUDED_PATH_PARTS = (
    "/espanol/",
    "reprinting-and-reusing",
    "brochures-and-fact-sheets",
    "spanish-listing",
    "infographic",
)
NIMH_CATEGORY_RULES = [
    ("psychotherapies", "self_help", ["心理治疗", "谈话治疗", "CBT", "咨询", "治疗类型"]),
    ("mental-health-medications", "medication", ["精神科药物", "心理药物", "抗抑郁药", "用药", "副作用"]),
    ("brain-stimulation", "medication", ["脑刺激疗法", "电休克", "TMS", "治疗"]),
    ("technology-and-the-future", "self_help", ["数字心理健康", "心理健康技术", "App", "远程治疗"]),
    ("covid-19", "coping", ["疫情", "COVID", "压力", "孤独", "心理健康"]),
    ("caring-for-your-mental-health", "self_help", ["照顾心理健康", "自助", "压力", "求助"]),
    ("child-and-adolescent", "teen", ["儿童", "青少年", "心理健康", "家长", "学校"]),
    ("men-and-mental-health", "emotion", ["男性心理健康", "男性", "求助", "压力"]),
    ("women-and-mental-health", "emotion", ["女性心理健康", "女性", "产后", "围产期"]),
    ("older-adults", "cognitive", ["老年心理健康", "老年", "认知", "孤独"]),
    ("substance-use-and-mental-health", "substance", ["物质使用", "成瘾", "共病", "双重诊断"]),
    ("anxiety", "emotion", ["焦虑", "担心", "紧张", "anxiety"]),
    ("generalized-anxiety", "emotion", ["广泛性焦虑", "焦虑", "担心"]),
    ("panic", "emotion", ["惊恐", "惊恐发作", "panic"]),
    ("social-anxiety", "relationship", ["社交焦虑", "害羞", "社交"]),
    ("depression", "emotion", ["抑郁", "低落", "心境", "depression"]),
    ("bipolar", "emotion", ["双相", "躁郁", "情绪波动"]),
    ("ocd", "emotion", ["强迫", "反复确认", "侵入想法"]),
    ("ptsd", "emotion", ["创伤", "PTSD", "应激"]),
    ("stress", "emotion", ["压力", "应激", "stress"]),
    ("suicide", "safety", ["自杀", "危机", "988", "安全"]),
    ("eating", "emotion", ["进食障碍", "饮食", "身体形象"]),
    ("adhd", "teen", ["注意力", "ADHD", "多动", "青少年"]),
    ("autism", "teen", ["自闭症", "谱系", "儿童", "青少年"]),
    ("children", "teen", ["儿童", "青少年", "心理健康", "学校"]),
    ("adolescents", "teen", ["儿童", "青少年", "心理健康", "学校"]),
    ("schizophrenia", "emotion", ["精神分裂症", "精神病性", "幻觉"]),
    ("psychosis", "emotion", ["精神病性", "早期精神病", "幻觉"]),
    ("borderline", "relationship", ["边缘型人格", "关系", "情绪调节"]),
    ("women", "emotion", ["女性心理健康", "产后", "围产期"]),
    ("men", "emotion", ["男性心理健康", "求助", "压力"]),
    ("treatments", "self_help", ["治疗", "心理治疗", "用药", "专业支持"]),
    ("trauma", "emotion", ["创伤", "应激", "灾难"]),
]


class ReadableHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title: str | None = None
        self.blocks: list[str] = []
        self._skip_depth = 0
        self._current_tag: str | None = None
        self._buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag in TEXT_TAGS or tag == "title":
            self._flush_current()
            self._current_tag = tag
            self._buffer = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
            return
        if self._skip_depth:
            return
        if tag == self._current_tag:
            self._flush_current()

    def handle_data(self, data: str) -> None:
        if self._skip_depth or self._current_tag is None:
            return
        self._buffer.append(data)

    def close(self) -> None:
        self._flush_current()
        super().close()

    def _flush_current(self) -> None:
        if self._current_tag is None:
            return
        text = _clean_text(" ".join(self._buffer))
        if text:
            if self._current_tag == "title":
                self.title = self.title or text
            elif self._current_tag == "h1" and not self.title:
                self.title = text
                self.blocks.append(text)
            else:
                self.blocks.append(text)
        self._current_tag = None
        self._buffer = []


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _html_to_text(value: str | None) -> str:
    if not value:
        return ""
    parser = ReadableHtmlParser()
    parser.feed(value)
    parser.close()
    if parser.blocks:
        return "\n".join(parser.blocks)
    return _clean_text(re.sub(r"<[^>]+>", " ", value))


def _fetch_readable_page(source_key: str, source_url: str) -> dict:
    _validate_source_url(source_key, source_url)
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(source_url, headers={"User-Agent": "knowledge-beta-import/0.1"})
        response.raise_for_status()

    parser = ReadableHtmlParser()
    parser.feed(response.text)
    parser.close()
    blocks = [block for block in parser.blocks if len(block) >= 24]
    if not blocks:
        raise ValueError("No readable text blocks found in fetched page.")
    return {
        "title": parser.title or blocks[0][:120],
        "blocks": blocks,
        "text": "\n".join(blocks),
    }


def _json_from_model_text(text: str) -> dict:
    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("LLM draft must be a JSON object.")
    return data


async def _rewrite_with_llm(*, source_title: str, source_text: str) -> dict | None:
    if not deepseek_client.is_configured:
        return None

    prompt = (
        "你是心理健康知识库编辑。请把英文开放资料改写为中文科普草稿，不能新增诊断、处方或治疗承诺。"
        "输出严格 JSON，字段包括 title, summary_30s, explanation_3min, common_misunderstandings, actions, "
        "seek_help_when, tags。actions、seek_help_when、tags 必须是字符串数组。"
    )
    content = (
        f"来源标题：{source_title}\n\n"
        f"来源正文节选：\n{source_text[:12000]}"
    )
    response = await deepseek_client.chat(
        [
            {"role": "system", "content": prompt},
            {"role": "user", "content": content},
        ],
        temperature=0.2,
        max_tokens=1200,
    )
    if not response:
        return None
    return _json_from_model_text(response)


def _fallback_draft_from_page(*, source_title: str, source_text: str) -> dict:
    excerpt = source_text[:1800]
    return {
        "title": source_title[:120],
        "summary_30s": f"待人工中文改写：{excerpt[:260]}",
        "explanation_3min": f"待人工审核和中文改写。原始资料节选：{excerpt}",
        "common_misunderstandings": [],
        "actions": ["待人工审核后补充可执行建议"],
        "seek_help_when": ["若涉及自伤风险、现实安全或明显功能受损，请优先联系现实支持或专业人员"],
        "tags": [],
    }


def _csv_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "topic"


def _latest_medlineplus_compressed_xml_url() -> str:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(MEDLINEPLUS_XML_INDEX_URL, headers={"User-Agent": "knowledge-beta-import/0.1"})
        response.raise_for_status()
    match = re.search(r'href="([^"]*mplus_topics_compressed_\d{4}-\d{2}-\d{2}\.zip)"', response.text)
    if not match:
        raise ValueError("Could not find the latest MedlinePlus compressed health topic XML URL.")
    href = match.group(1)
    if href.startswith("http"):
        return href
    return MEDLINEPLUS_XML_BASE_URL + href.lstrip("/")


def _read_medlineplus_topics(xml_zip_url: str | None = None) -> tuple[list[ET.Element], str]:
    url = xml_zip_url or _latest_medlineplus_compressed_xml_url()
    with httpx.Client(timeout=90.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "knowledge-beta-import/0.1"})
        response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        xml_names = [name for name in archive.namelist() if name.endswith(".xml")]
        if not xml_names:
            raise ValueError("MedlinePlus compressed XML did not contain an XML file.")
        root = ET.fromstring(archive.read(xml_names[0]))
    return list(root.findall("health-topic")), url


def _medlineplus_topic_groups(topic: ET.Element) -> list[str]:
    return [_clean_text(group.text or "") for group in topic.findall("group") if _clean_text(group.text or "")]


def _medlineplus_topic_tags(topic: ET.Element) -> list[str]:
    title = str(topic.attrib.get("title", "")).strip()
    zh_title, _ = MEDLINEPLUS_TITLE_TRANSLATIONS.get(title, (title, "emotion"))
    tags = [title, zh_title, *MEDLINEPLUS_EXTRA_TAGS.get(title, [])]
    tags.extend(_clean_text(item.text or "") for item in topic.findall("also-called") if _clean_text(item.text or ""))
    groups = _medlineplus_topic_groups(topic)
    tags.extend(groups)
    for group in groups:
        tags.extend(MEDLINEPLUS_GROUP_TAGS.get(group, []))

    deduped: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        normalized = tag.strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(tag.strip())
    return deduped[:18]


def _medlineplus_category_for(title: str, groups: list[str]) -> tuple[str, str]:
    if title in MEDLINEPLUS_TITLE_TRANSLATIONS:
        category = MEDLINEPLUS_TITLE_TRANSLATIONS[title][1]
    elif "Children and Teenagers" in groups:
        category = "teen"
    elif "Social/Family Issues" in groups:
        category = "relationship"
    elif "Safety Issues" in groups:
        category = "safety"
    elif "Fitness and Exercise" in groups or "Wellness and Lifestyle" in groups or "Food and Nutrition" in groups:
        category = "self_help"
    elif "Older Adults" in groups:
        category = "cognitive"
    else:
        category = "coping"
    audience = "teen" if category == "teen" else "all"
    return category, audience


def _medlineplus_record_from_topic(topic: ET.Element, *, resolved_url: str) -> dict | None:
    title = str(topic.attrib.get("title", "")).strip()
    source_url = str(topic.attrib.get("url", "")).strip()
    summary = _html_to_text((topic.findtext("full-summary") or "").strip())
    if not title or not source_url or len(summary) < 120:
        return None

    groups = _medlineplus_topic_groups(topic)
    zh_title, fallback_category = MEDLINEPLUS_TITLE_TRANSLATIONS.get(title, (title, "coping"))
    category, audience = _medlineplus_category_for(title, groups)
    if fallback_category != "coping":
        category = fallback_category
        audience = "teen" if category == "teen" else audience

    topic_id = str(topic.attrib.get("id", "")).strip()
    slug = f"medlineplus-{_slugify(title)}-{topic_id or _slugify(source_url)}"
    source_title = f"MedlinePlus Health Topic: {title}"
    return {
        "slug": slug,
        "title": zh_title,
        "category": category[:32],
        "audience": audience,
        "summary_30s": summary[:320],
        "explanation_3min": summary[:4000],
        "advanced_text": f"MedlinePlus source topic: {title}. XML batch source: {resolved_url}",
        "common_misunderstandings": [
            "这条知识用于科普和自助理解，不能替代医生、心理咨询师或其他专业人员的评估。",
            "不要仅凭一条资料给自己或他人下诊断。",
        ],
        "actions": [
            "先把最相关的症状、持续时间和影响记录下来。",
            "如果内容与你的情况相似，可以把它带到咨询对话里继续梳理。",
            "需要诊断、治疗或用药建议时，请联系现实中的专业人员。",
        ],
        "seek_help_when": _medlineplus_seek_help(title),
        "tags": _medlineplus_topic_tags(topic),
        "source_url": source_url,
        "source_title": source_title,
        "reviewer_note": "Auto-published from MedlinePlus public-domain health topic XML.",
    }


def _medlineplus_seek_help(title: str) -> list[str]:
    if title in {"Self-Harm", "Suicide"}:
        return [
            "如果已经有自伤或自杀计划、工具或冲动，请立即联系当地紧急服务或身边可信任的人。",
            "如果当前环境不安全，请优先离开危险物品和危险地点。",
        ]
    return [
        "症状持续影响睡眠、学习、工作或关系时，建议联系现实中的专业人员。",
        "如果出现自伤想法、明显失控感或现实安全风险，请优先使用危机支持资源。",
    ]


def _build_medlineplus_mental_health_records(
    *,
    include_substance: bool,
    include_adjacent: bool,
    limit: int | None,
    xml_zip_url: str | None,
) -> list[dict]:
    topics, resolved_url = _read_medlineplus_topics(xml_zip_url)
    include_groups = set(MEDLINEPLUS_MENTAL_GROUPS)
    if include_substance:
        include_groups.update(MEDLINEPLUS_SUBSTANCE_GROUPS)

    records: list[dict] = []
    for topic in topics:
        if topic.attrib.get("language") != "English":
            continue
        groups = _medlineplus_topic_groups(topic)
        title = str(topic.attrib.get("title", "")).strip()
        if not include_groups.intersection(groups) and not (include_adjacent and title in MEDLINEPLUS_ADJACENT_TITLES):
            continue

        record = _medlineplus_record_from_topic(topic, resolved_url=resolved_url)
        if record is None:
            continue
        records.append(record)
        if limit and len(records) >= limit:
            break

    if not records:
        raise ValueError("No MedlinePlus mental health topics matched the import filters.")
    return records


def _high_confidence_score(topic: ET.Element, existing_slugs: set[str]) -> int:
    if topic.attrib.get("language") != "English":
        return -1
    title = str(topic.attrib.get("title", "")).strip()
    topic_id = str(topic.attrib.get("id", "")).strip()
    source_url = str(topic.attrib.get("url", "")).strip()
    slug = f"medlineplus-{_slugify(title)}-{topic_id or _slugify(source_url)}"
    if not title or slug in existing_slugs:
        return -1

    groups = _medlineplus_topic_groups(topic)
    haystack = " ".join([title, *groups, *[(item.text or "") for item in topic.findall("also-called")]]).lower()
    if title not in MEDLINEPLUS_HIGH_CONFIDENCE_TITLES and not any(keyword in haystack for keyword in MEDLINEPLUS_HIGH_CONFIDENCE_KEYWORDS):
        return -1
    score = 0
    if title in MEDLINEPLUS_HIGH_CONFIDENCE_TITLES:
        score += 48
    score += 30 * len(MEDLINEPLUS_HIGH_CONFIDENCE_GROUPS.intersection(groups))
    score += 18 * sum(1 for keyword in MEDLINEPLUS_HIGH_CONFIDENCE_KEYWORDS if keyword in haystack)
    if title in MEDLINEPLUS_TITLE_TRANSLATIONS:
        score += 24
    if any(group in groups for group in ("Wellness and Lifestyle", "Social/Family Issues", "Children and Teenagers")):
        score += 12
    medical_only_groups = {
        "Infections",
        "Cancers",
        "Blood, Heart and Circulation",
        "Ear, Nose and Throat",
        "Mouth and Teeth",
        "Skin, Hair and Nails",
        "Endocrine System",
        "Diabetes Mellitus",
        "Immune System",
        "Genetics/Birth Defects",
        "Digestive System",
        "Kidneys and Urinary System",
        "Lungs and Breathing",
    }
    if medical_only_groups.intersection(groups) and title not in MEDLINEPLUS_HIGH_CONFIDENCE_TITLES:
        return -1
    if "Medical Encyclopedia" in haystack:
        score -= 80
    summary = _html_to_text((topic.findtext("full-summary") or "").strip())
    if len(summary) < 120:
        return -1
    return score


def _existing_medlineplus_slugs() -> set[str]:
    with SessionLocal() as db:
        return set(
            db.scalars(
                select(KnowledgeArticle.slug)
                .join(KnowledgeSource)
                .where(KnowledgeSource.source_key == "medlineplus_public_domain")
            )
        )


def _build_medlineplus_high_confidence_records(*, limit: int, xml_zip_url: str | None) -> list[dict]:
    topics, resolved_url = _read_medlineplus_topics(xml_zip_url)
    existing_slugs = _existing_medlineplus_slugs()
    scored_topics = [
        (_high_confidence_score(topic, existing_slugs), topic)
        for topic in topics
    ]
    scored_topics = [(score, topic) for score, topic in scored_topics if score >= 48]
    scored_topics.sort(key=lambda item: (-item[0], item[1].attrib.get("title", "")))

    records: list[dict] = []
    for _, topic in scored_topics:
        record = _medlineplus_record_from_topic(topic, resolved_url=resolved_url)
        if record is None:
            continue
        records.append(record)
        if len(records) >= limit:
            break

    if len(records) < limit:
        raise ValueError(f"Only found {len(records)} new high-confidence MedlinePlus topics; requested {limit}.")
    return records


def _absolute_nimh_url(href: str) -> str:
    if href.startswith("https://www.nimh.nih.gov/"):
        return href
    if href.startswith("/"):
        return f"{NIMH_BASE_URL}{href}"
    return href


def _nimh_links_from_page(url: str, *, path_prefix: str = "/health/publications") -> list[tuple[str, str]]:
    with httpx.Client(timeout=30.0, follow_redirects=True) as client:
        response = client.get(url, headers={"User-Agent": "knowledge-beta-import/0.1"})
        response.raise_for_status()
    links: list[tuple[str, str]] = []
    for match in re.finditer(r'href="([^"]+)"[^>]*>(.*?)</a>', response.text, re.S | re.I):
        href = _absolute_nimh_url(match.group(1).split("#", 1)[0])
        label = _clean_text(re.sub(r"<[^>]+>", " ", match.group(2)))
        if href.startswith(f"{NIMH_BASE_URL}{path_prefix}"):
            links.append((href, label))
    return links


def _is_nimh_listing_url(url: str) -> bool:
    path = urlparse(url).path
    return path.endswith("-listing") or path.endswith("/brochures-and-fact-sheets-in-english")


def _is_importable_nimh_publication_url(url: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != "www.nimh.nih.gov":
        return False
    path = parsed.path
    if not path.startswith("/health/publications/"):
        return False
    if path.endswith("-listing"):
        return False
    if any(part in path for part in NIMH_EXCLUDED_PATH_PARTS):
        return False
    return True


def _nimh_category_for(url: str, listing_label: str, page_title: str) -> tuple[str, list[str], str]:
    haystack = " ".join([urlparse(url).path.lower(), listing_label.lower(), page_title.lower()])
    for needle, category, tags in NIMH_CATEGORY_RULES:
        if needle in haystack:
            return category, tags, "teen" if category == "teen" else "all"
    return "emotion", ["心理健康", "NIMH", listing_label or page_title], "all"


def _build_nimh_publication_records(*, limit: int | None) -> list[dict]:
    listing_links = [
        (url, label)
        for url, label in _nimh_links_from_page(NIMH_PUBLICATIONS_URL)
        if _is_nimh_listing_url(url) and "/espanol/" not in url
    ]
    seen_publication_urls: set[str] = set()
    publication_candidates: list[tuple[str, str]] = []
    for listing_url, listing_label in listing_links:
        for href, label in _nimh_links_from_page(listing_url):
            if not _is_importable_nimh_publication_url(href):
                continue
            if href in seen_publication_urls:
                continue
            seen_publication_urls.add(href)
            publication_candidates.append((href, listing_label or label))

    records: list[dict] = []
    for source_url, listing_label in publication_candidates:
        try:
            page = _fetch_readable_page("nimh_public_domain", source_url)
        except Exception as exc:
            print(f"Skipping NIMH URL {source_url}: {exc}", file=sys.stderr)
            continue
        source_title = page["title"]
        text = page["text"]
        if len(text) < 700:
            continue
        category, tags, audience = _nimh_category_for(source_url, listing_label, source_title)
        slug = f"nimh-{_slugify(urlparse(source_url).path.rsplit('/', 1)[-1])}"
        records.append(
            {
                "slug": slug,
                "title": source_title[:120],
                "category": category,
                "audience": audience,
                "summary_30s": text[:320],
                "explanation_3min": text[:5000],
                "advanced_text": f"NIMH publication text imported from {source_url}",
                "common_misunderstandings": [
                    "这条知识用于科普和自助理解，不能替代专业评估或治疗建议。",
                    "NIMH 文本可复用，但页面图片不进入知识库。",
                ],
                "actions": [
                    "把与你相关的症状、持续时间和影响记录下来。",
                    "如果内容与你的情况相似，可以把它带到咨询对话里继续梳理。",
                    "需要诊断、治疗或用药建议时，请联系现实中的专业人员。",
                ],
                "seek_help_when": _medlineplus_seek_help("Suicide" if category == "safety" else source_title),
                "tags": [*tags, "NIMH", listing_label],
                "source_url": source_url,
                "source_title": source_title,
                "reviewer_note": "Auto-published from NIMH public-domain publication text; images excluded.",
            }
        )
        if limit and len(records) >= limit:
            break

    if not records:
        raise ValueError("No NIMH publication pages matched the import filters.")
    return records


def _build_nimh_topic_records(*, limit: int | None) -> list[dict]:
    topic_links = []
    seen: set[str] = set()
    for href, label in _nimh_links_from_page(NIMH_TOPICS_URL, path_prefix="/health/topics"):
        url = _absolute_nimh_url(href)
        path = urlparse(url).path
        if not path.startswith("/health/topics/") or path == "/health/topics":
            continue
        if "/espanol/" in path or url in seen:
            continue
        seen.add(url)
        topic_links.append((url, label))

    records: list[dict] = []
    for source_url, label in topic_links:
        try:
            page = _fetch_readable_page("nimh_public_domain", source_url)
        except Exception as exc:
            print(f"Skipping NIMH topic URL {source_url}: {exc}", file=sys.stderr)
            continue
        source_title = page["title"] or label
        text = page["text"]
        if len(text) < 500:
            continue
        category, tags, audience = _nimh_category_for(source_url, label, source_title)
        slug = f"nimh-topic-{_slugify(urlparse(source_url).path.rsplit('/', 1)[-1])}"
        records.append(
            {
                "slug": slug,
                "title": source_title[:120],
                "category": category,
                "audience": audience,
                "summary_30s": text[:320],
                "explanation_3min": text[:5000],
                "advanced_text": f"NIMH health topic text imported from {source_url}",
                "common_misunderstandings": [
                    "这条知识用于科普和自助理解，不能替代专业评估或治疗建议。",
                    "NIMH 页面图片不进入知识库。",
                ],
                "actions": [
                    "把与你相关的症状、持续时间和影响记录下来。",
                    "如果内容与你的情况相似，可以把它带到咨询对话里继续梳理。",
                    "需要诊断、治疗或用药建议时，请联系现实中的专业人员。",
                ],
                "seek_help_when": _medlineplus_seek_help("Suicide" if category == "safety" else source_title),
                "tags": [*tags, "NIMH", "health topics", label],
                "source_url": source_url,
                "source_title": source_title,
                "reviewer_note": "Auto-published from NIMH public-domain health topic text; images excluded.",
            }
        )
        if limit and len(records) >= limit:
            break

    if not records:
        raise ValueError("No NIMH health topic pages matched the import filters.")
    return records


def _build_record_from_url(args: argparse.Namespace) -> dict:
    page = _fetch_readable_page(args.source, args.fetch_url)
    draft = asyncio.run(_rewrite_with_llm(source_title=page["title"], source_text=page["text"])) if args.rewrite_with_llm else None
    if draft is None:
        draft = _fallback_draft_from_page(source_title=page["title"], source_text=page["text"])

    tags = _csv_list(args.tags)
    if tags:
        draft["tags"] = tags

    return {
        "slug": args.slug,
        "title": args.title or str(draft.get("title") or page["title"]),
        "category": args.category,
        "audience": args.audience,
        "summary_30s": str(draft.get("summary_30s", "")).strip(),
        "explanation_3min": str(draft.get("explanation_3min", "")).strip(),
        "advanced_text": str(draft.get("advanced_text", "")).strip() or None,
        "common_misunderstandings": draft.get("common_misunderstandings") or [],
        "actions": draft.get("actions") or [],
        "seek_help_when": draft.get("seek_help_when") or [],
        "tags": draft.get("tags") or [],
        "source_url": args.fetch_url,
        "source_title": page["title"],
        "reviewer_note": "Imported as draft from whitelisted URL; requires human review before publishing.",
    }


def _load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("items", [])
    if not isinstance(data, list):
        raise ValueError("Input JSON must be a list or an object with an 'items' list.")
    return [item for item in data if isinstance(item, dict)]


def _source_payload(source_key: str) -> dict:
    for payload in SEED_SOURCES:
        if payload["source_key"] == source_key:
            return payload
    raise ValueError(f"Unsupported source_key: {source_key}")


def _validate_source_url(source_key: str, source_url: str | None) -> None:
    if source_key == "internal_curated":
        return
    if not source_url:
        raise ValueError("External source records must include source_url.")
    host = urlparse(source_url).netloc.lower()
    allowed_hosts = ALLOWED_HOSTS.get(source_key, set())
    if host not in allowed_hosts:
        raise ValueError(f"source_url host '{host}' is not allowed for {source_key}.")


def _required_text(record: dict, key: str) -> str:
    value = str(record.get(key, "")).strip()
    if not value:
        raise ValueError(f"Missing required field: {key}")
    return value


def _list_value(record: dict, key: str) -> list[str]:
    value = record.get(key, [])
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def import_records(*, source_key: str, records: list[dict], publish_reviewed: bool, dry_run: bool) -> dict[str, int]:
    source_payload = _source_payload(source_key)
    status = "published" if publish_reviewed else "draft"
    review_status = "published" if publish_reviewed else "draft"
    counts = {"created": 0, "updated": 0, "skipped": 0}

    with SessionLocal() as db:
        source = db.scalar(select(KnowledgeSource).where(KnowledgeSource.source_key == source_key))
        if source is None:
            source = KnowledgeSource(**source_payload)
            db.add(source)
            db.flush()
        if not dry_run:
            source.retrieved_at = utcnow()

        for record in records:
            source_url = str(record.get("source_url", "")).strip() or None
            _validate_source_url(source_key, source_url)
            slug = _required_text(record, "slug")
            title = _required_text(record, "title")
            summary_30s = _required_text(record, "summary_30s")
            explanation_3min = _required_text(record, "explanation_3min")
            category = str(record.get("category", "emotion")).strip() or "emotion"
            audience = str(record.get("audience", "all")).strip() or "all"
            if audience not in {"all", "teen", "adult"}:
                raise ValueError(f"Invalid audience for {slug}: {audience}")

            payload = {
                "source_id": source.id,
                "slug": slug,
                "title": title,
                "category": category,
                "audience": audience,
                "summary_30s": summary_30s,
                "explanation_3min": explanation_3min,
                "advanced_text": str(record.get("advanced_text", "")).strip() or None,
                "common_misunderstandings": _list_value(record, "common_misunderstandings"),
                "actions": _list_value(record, "actions"),
                "seek_help_when": _list_value(record, "seek_help_when"),
                "source_refs": [
                    {
                        "source_name": source.name,
                        "source_url": source_url or source.base_url,
                        "license": str(source_payload["license"]),
                        "source_title": str(record.get("source_title", title)).strip(),
                    }
                ],
                "tags": _list_value(record, "tags"),
                "status": status,
                "review_status": review_status,
                "license": str(source_payload["license"]),
                "source_url": source_url or source.base_url,
                "reviewer_note": str(record.get("reviewer_note", "")).strip() or None,
                "published_at": utcnow() if publish_reviewed else None,
            }

            article = db.scalar(select(KnowledgeArticle).where(KnowledgeArticle.slug == slug))
            if article is None:
                if dry_run:
                    counts["created"] += 1
                    continue
                article = KnowledgeArticle(**payload)
                db.add(article)
                db.flush()
                _sync_article_chunks(db, article)
                counts["created"] += 1
                continue

            if article.review_status == "published" and not publish_reviewed:
                counts["skipped"] += 1
                continue

            if dry_run:
                counts["updated"] += 1
                continue

            for key, value in payload.items():
                setattr(article, key, value)
            _sync_article_chunks(db, article)
            counts["updated"] += 1

        if not dry_run:
            db.commit()

    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description="Import knowledge records from whitelisted open sources.")
    parser.add_argument("--source", required=True, choices=sorted(ALLOWED_HOSTS.keys()))
    parser.add_argument("--input-json", type=Path, help="JSON list or object with an items list.")
    parser.add_argument("--fetch-url", help="Fetch one whitelisted source URL and import it as a draft.")
    parser.add_argument(
        "--batch-medlineplus-mental-health",
        action="store_true",
        help="Import MedlinePlus Mental Health and Behavior health topic summaries in batch.",
    )
    parser.add_argument(
        "--batch-medlineplus-high-confidence",
        action="store_true",
        help="Import new high-confidence psychology-adjacent MedlinePlus health topic summaries.",
    )
    parser.add_argument(
        "--batch-nimh-publications",
        action="store_true",
        help="Import NIMH mental health publication pages in batch, excluding images and non-publication pages.",
    )
    parser.add_argument(
        "--batch-nimh-topics",
        action="store_true",
        help="Import NIMH mental health topic pages in batch, excluding images.",
    )
    parser.add_argument("--medlineplus-xml-url", help="Override the latest MedlinePlus compressed health topic XML zip URL.")
    parser.add_argument("--include-substance", action="store_true", help="Also include MedlinePlus Substance Use and Disorders topics.")
    parser.add_argument("--include-adjacent", action="store_true", help="Also include whitelisted psychology-adjacent MedlinePlus topics.")
    parser.add_argument("--limit", type=int, help="Limit records for batch imports.")
    parser.add_argument("--slug", help="Required with --fetch-url.")
    parser.add_argument("--title", help="Optional reviewed title override for --fetch-url.")
    parser.add_argument("--category", default="emotion", help="Category for --fetch-url drafts.")
    parser.add_argument("--audience", default="all", choices=["all", "teen", "adult"], help="Audience for --fetch-url drafts.")
    parser.add_argument("--tags", default="", help="Comma-separated tags for --fetch-url drafts.")
    parser.add_argument("--rewrite-with-llm", action="store_true", help="Use configured DeepSeek to create a Chinese rewrite draft.")
    parser.add_argument("--output-json", type=Path, help="Write normalized draft records before importing.")
    parser.add_argument("--no-import", action="store_true", help="Only write --output-json; do not write to the database.")
    parser.add_argument("--publish-reviewed", action="store_true", help="Mark imported records as published after human review.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    import_modes = [
        bool(args.input_json),
        bool(args.fetch_url),
        bool(args.batch_medlineplus_mental_health),
        bool(args.batch_medlineplus_high_confidence),
        bool(args.batch_nimh_publications),
        bool(args.batch_nimh_topics),
    ]
    if sum(import_modes) != 1:
        parser.error("Provide exactly one import mode.")
    if args.fetch_url and not args.slug:
        parser.error("--slug is required with --fetch-url.")
    if args.fetch_url and args.source == "internal_curated":
        parser.error("--fetch-url is only available for external whitelisted open sources.")
    if args.batch_medlineplus_mental_health and args.source != "medlineplus_public_domain":
        parser.error("--batch-medlineplus-mental-health requires --source medlineplus_public_domain.")
    if args.batch_medlineplus_high_confidence and args.source != "medlineplus_public_domain":
        parser.error("--batch-medlineplus-high-confidence requires --source medlineplus_public_domain.")
    if args.batch_nimh_publications and args.source != "nimh_public_domain":
        parser.error("--batch-nimh-publications requires --source nimh_public_domain.")
    if args.batch_nimh_topics and args.source != "nimh_public_domain":
        parser.error("--batch-nimh-topics requires --source nimh_public_domain.")
    if args.no_import and not args.output_json:
        parser.error("--no-import requires --output-json.")
    if args.fetch_url and args.publish_reviewed:
        parser.error("--fetch-url imports drafts only. Review the generated record, then re-run with --input-json --publish-reviewed.")

    init_db()
    if args.fetch_url:
        records = [_build_record_from_url(args)]
    elif args.batch_medlineplus_mental_health:
        records = _build_medlineplus_mental_health_records(
            include_substance=args.include_substance,
            include_adjacent=args.include_adjacent,
            limit=args.limit,
            xml_zip_url=args.medlineplus_xml_url,
        )
    elif args.batch_medlineplus_high_confidence:
        records = _build_medlineplus_high_confidence_records(
            limit=args.limit or 100,
            xml_zip_url=args.medlineplus_xml_url,
        )
    elif args.batch_nimh_publications:
        records = _build_nimh_publication_records(limit=args.limit)
    elif args.batch_nimh_topics:
        records = _build_nimh_topic_records(limit=args.limit)
    else:
        records = _load_records(args.input_json)
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps({"items": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.no_import:
        print(json.dumps({"created": 0, "updated": 0, "skipped": 0, "output_json": str(args.output_json)}, ensure_ascii=False, indent=2))
        return

    counts = import_records(
        source_key=args.source,
        records=records,
        publish_reviewed=args.publish_reviewed,
        dry_run=args.dry_run,
    )
    print(json.dumps(counts, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
