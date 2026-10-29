import json
import requests

def list_models(base_url: str, key: str) -> list[str]:
    """Read model IDs exposed by an OpenAI-compatible gateway."""
    if not base_url.strip(): raise ValueError("请填写接口地址")
    if not key.strip(): raise ValueError("请先填写接口 Key")
    url=base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"): url=url[:-len("/chat/completions")]
    if not url.endswith("/v1"): url += "/v1"
    response=requests.get(url+"/models",headers={"Authorization":f"Bearer {key.strip()}","Content-Type":"application/json"},timeout=30)
    if not response.ok: raise ValueError(f"模型列表请求失败（HTTP {response.status_code}）：{_response_error(response)}")
    try: data=response.json().get("data",[])
    except (TypeError,ValueError): raise ValueError("模型列表返回格式无效")
    models=sorted({str(item.get("id")) for item in data if isinstance(item,dict) and item.get("id")},key=str.casefold)
    if not models: raise ValueError("接口没有返回可用模型")
    return models

def _json_content(value: str) -> dict:
    text=str(value or "").strip()
    if text.startswith("```"):
        text=text.split("\n",1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"): text=text.rstrip()[:-3]
    start=text.find("{"); end=text.rfind("}")
    if start < 0 or end < start: raise ValueError("模型没有返回有效的 JSON 对象")
    try: result=json.loads(text[start:end+1])
    except json.JSONDecodeError as exc: raise ValueError(f"模型返回的 JSON 无法解析：{exc.msg}") from exc
    if not isinstance(result,dict): raise ValueError("模型返回结果必须是 JSON 对象")
    return result

def _response_error(response) -> str:
    try:
        data=response.json(); detail=data.get("error",data)
        if isinstance(detail,dict): detail=detail.get("message") or detail.get("code") or json.dumps(detail,ensure_ascii=False)
        return str(detail)[:800]
    except Exception:
        return str(getattr(response,"text","") or f"HTTP {response.status_code}")[:800]

def chat(base_url: str, key: str, model: str, system: str, user: str, reasoning_effort: str | None = None) -> dict:
    if not base_url or not model: raise ValueError("请配置 LLM 接口和模型")
    url=base_url.rstrip("/")
    if not url.endswith("/chat/completions"): url += "/chat/completions"
    headers={"Content-Type":"application/json"}
    if key: headers["Authorization"]=f"Bearer {key}"
    base={"model":model,"messages":[{"role":"system","content":system},{"role":"user","content":user}]}
    attempts=[]
    first={**base,"response_format":{"type":"json_object"}}
    if reasoning_effort: first["reasoning_effort"]=reasoning_effort
    attempts.append(first)
    second=dict(base)
    if reasoning_effort: second["reasoning_effort"]=reasoning_effort
    attempts.append(second)
    if reasoning_effort: attempts.append(dict(base))
    last=None
    for position,body in enumerate(attempts):
        r=requests.post(url,headers=headers,json=body,timeout=180); last=r
        if r.ok:
            try: content=r.json()["choices"][0]["message"]["content"]
            except (KeyError,IndexError,TypeError,ValueError) as exc: raise ValueError("模型接口返回格式不完整") from exc
            return _json_content(content)
        if r.status_code != 400 or position == len(attempts)-1: break
    raise ValueError(f"模型接口请求失败（HTTP {last.status_code}）：{_response_error(last)}")

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
    system=("我会发给你一段解说视频的 .srt 字幕文件。任务：只通过整段删除字幕行进行剪辑，不改任何字句，把成片时长控制在原视频60%~80%的区间内。剪辑规则（从高到低优先级）：\n"
            "1.时长是最高优先级：结合srt文件中给出的时间轴，剪辑后成品保留60%~80%之间的时间即可，不需要尽量接近某个具体时长\n"
            "2.剪辑方式：只能整段删字幕；每次删除要删掉至少连续 3 条字幕行；整个视频里要有至少 3 处这样的删除。\n"
            "3.内容取舍原则（帮助你更快判断）：优先保留：开头吸引人的引子、核心观点/结论、关键案例或反转、结尾总结；优先删除：重复解释、赘述、口头禅、无信息填充。\n"
            "4.输出格式（非常重要）：\n用“保留/删除 + 段号范围 + 时间范围 + 首两句文字”的形式输出，例如：\n"
            "保留 1 段~10 段：\n（第 1 段起始时间） --> （第 10 段结束时间）\n只输出第 1 段、第2段的文字内容\n"
            "删除 11 段~20 段：\n（第 11 段起始时间） --> （第 20 段结束时间）\n只输出第 11 段、第12段的文字内容\n"
            "不要输出任何原因解释或分析过程。\n"
            "5.最后单独写一行：\n“预计剪掉时长：XX 分 XX 秒；保留时长：XX 分 XX 秒。”\n时间可以精确到秒，不必精确到毫秒。\n"
            "为便于程序执行，请把最终选择仅编码为JSON对象，不要Markdown和解释，格式必须为 {\"delete_ranges\":[{\"start\":11,\"end\":20}]}。"
            "start和end使用输入数组中的position；删除范围不能重叠或相邻。程序会根据JSON按上述格式保存完整剪辑结果。")
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
