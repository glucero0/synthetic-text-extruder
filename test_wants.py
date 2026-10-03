import sys
sys.path.insert(0, '.')
from synthetic_text_extruder.collection_jobs import wants_collection_job, expand_collection_members, plan_collection_job
from synthetic_text_extruder.studio_sources import creation_source_modality

sources = [{'id': '1', 'modality': 'text', 'title': 'code.txt'}]
print("wants_collection_job:", wants_collection_job('create a pdf', sources))

members = expand_collection_members(sources)
plan = plan_collection_job('create a pdf', has_collection=False)
print("plan:", plan)
kind = str(plan.get("kind") or "")
print("kind:", kind)
visuals = [s for s in members if creation_source_modality(s) in {"image", "video", "pdf", "audio"}]
images = [s for s in members if creation_source_modality(s) == "image"]
print("visuals:", len(visuals))
print("images:", len(images))
