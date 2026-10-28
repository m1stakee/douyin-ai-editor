import json
import requests

def chat(base_url: str, key: str, model: str, system: str, user: str, reasoning_effort: str | None = None) -> dict:
    if not base_url or not model: raise ValueError("请配置 LLM 接口和模型")
    url=base_url.rstrip("/")
    if not url.endswith("/chat/completions"): url += "/chat/completions"
    headers={"Content-Type":"application/json"}
    if key: headers["Authorization"]=f"Bearer {key}"
    body={"model":model,"temperature":0.2,"messages":[{"role":"system","content":system},{"role":"user","content":user}],"response_format":{"type":"json_object"}}
    if reasoning_effort: body["reasoning_effort"]=reasoning_effort
    r=requests.post(url,headers=headers,json=body,timeout=60); r.raise_for_status()
    content=r.json()["choices"][0]["message"]["content"]
    return json.loads(content)

def rewrite_text(text: str, prompt: str, key: str, model: str, base_url: str | None = None, reasoning_effort: str | None = None) -> str:
    if not key.strip(): raise ValueError("请先配置 API Key")
    if not model.strip(): raise ValueError("请输入模型名称")
    url=(base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1").strip().rstrip("/")
    if not url: raise ValueError("请配置 API 地址")
    if not url.endswith("/chat/completions"): url += "/chat/completions"
    body={"model":model,"temperature":0.7,"messages":[{"role":"system","content":prompt.strip()},{"role":"user","content":text.strip()}]}
    if "ark.cn-beijing.volces.com" in url: body["thinking"]={"type":"disabled"}
    if reasoning_effort: body["reasoning_effort"]=reasoning_effort
    response=requests.post(url,headers={"Authorization":f"Bearer {key.strip()}","Content-Type":"application/json"},json=body,timeout=120)
    response.raise_for_status()
    content=response.json()["choices"][0]["message"]["content"]
    if not isinstance(content,str) or not content.strip(): raise ValueError("模型接口返回了空文案")
    return content.strip()

def rewrite(segments, target_language, base_url, key, model, style="自然口播", length="保持原时长", reasoning_effort=None):
    system="你是短视频文案编辑。只返回 JSON，不要 Markdown。字段为 language 和 segments；segments 每项包含 id、source_ids、text、estimated_duration。"
    user=json.dumps({"target_language":target_language,"style":style,"length":length,"segments":segments},ensure_ascii=False)
    return chat(base_url,key,model,system,user,reasoning_effort)

def edit_plan(segments, scenes, rewrite_result, base_url, key, model, reasoning_effort=None):
    system="你是视频剪辑规划器。只返回 JSON。字段为 timeline、remove_scene_ids、notes。timeline 每项包含 scene_id、rewrite_segment_id、speed；speed 必须在 0.9 到 1.1。"
    user=json.dumps({"source_segments":segments,"scenes":scenes,"rewrite":rewrite_result},ensure_ascii=False)
    return chat(base_url,key,model,system,user,reasoning_effort)

def srt_deletion_plan(cues, duration, base_url, key, model, reasoning_effort=None, correction=""):
    system=("你是解说视频字幕剪辑规划器。只能通过整段删除字幕条目来剪辑，绝不能修改字幕文字。"
            "成片保留时长必须为原视频的60%到80%；每处删除至少连续3条字幕，整个视频至少3处删除。"
            "优先保留开头引子、核心观点或结论、关键案例或反转、结尾总结；优先删除重复解释、赘述、口头禅和无信息填充。"
            "只返回JSON对象，不要Markdown和解释。格式必须为 {\"delete_ranges\":[{\"start\":11,\"end\":20}]}。"
            "start和end是输入数组中的position，不是SRT原始编号；删除范围不能重叠或相邻。")
    payload={"video_duration_seconds":duration,"subtitles":[{"position":i,"start":x.start,"end":x.end,"text":x.text} for i,x in enumerate(cues,1)]}
    if correction: payload["previous_plan_error"]=correction
    result=chat(base_url,key,model,system,json.dumps(payload,ensure_ascii=False),reasoning_effort)
    ranges=result.get("delete_ranges")
    if not isinstance(ranges,list): raise ValueError("模型没有返回 delete_ranges")
    return ranges

def validate_plan(plan, scenes, rewrite_result, duration):
    scene_map={x["id"]:x for x in scenes}; seg_ids={x["id"] for x in rewrite_result["segments"]}
    if not isinstance(plan.get("timeline"),list) or not plan["timeline"]: raise ValueError("剪辑计划没有 timeline")
    normalized=[]
    for x in plan["timeline"]:
        if x.get("scene_id") not in scene_map: raise ValueError("剪辑计划引用了未知镜头")
        if x.get("rewrite_segment_id") not in seg_ids: raise ValueError("剪辑计划引用了未知文案片段")
        speed=float(x.get("speed",1.0))
        if not 0.9 <= speed <= 1.1: raise ValueError("播放速度必须在 0.9 到 1.1")
        s=scene_map[x["scene_id"]]
        if s["start"]<0 or s["end"]>duration or s["start"]>=s["end"]: raise ValueError("镜头时间范围无效")
        normalized.append({"scene":{"id":s["id"],"start":s["start"],"end":s["end"]},"rewrite_segment_id":x["rewrite_segment_id"],"speed":speed})
    return {"version":1,"timeline":normalized,"remove_scene_ids":plan.get("remove_scene_ids",[]),"notes":plan.get("notes",[])}
