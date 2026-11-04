"""Portable classroom bundles, with the legacy root JSON kept as an index."""
import json
import re
import shutil
import uuid
from pathlib import Path


def safe_name(value):
    name=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',value).strip(' .')[:70] or '未命名'
    if name.split('.')[0].upper() in {'CON','PRN','AUX','NUL',*(f'COM{i}' for i in range(1,10)),*(f'LPT{i}' for i in range(1,10))}:name='_'+name
    return name


def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    content=json.dumps(data,ensure_ascii=False,indent=2)
    if path.exists() and path.read_text('utf8')==content:return
    tmp=path.with_suffix('.tmp');tmp.write_text(content,'utf8');tmp.replace(path)


class ClassroomStore:
    def __init__(self,root,subjects):
        self.root=Path(root).resolve();self.subjects=subjects

    def subject_path(self,key):
        subject=next((s for s in self.subjects if s['id']==key),None)
        name=safe_name(subject['name'])+'__'+safe_name(subject['id'])[:8] if subject else '未分类'
        path=self.root/'课堂资料'/name;path.mkdir(parents=True,exist_ok=True);return path

    def delete(self, index):
        """Remove a classroom from live indexes, retaining its bundle locally."""
        index=Path(index).resolve()
        if index.parent!=self.root or index.suffix!='.json':
            raise ValueError('课堂索引不在笔记目录内')
        note=json.loads(index.read_text('utf8'))
        key=note.get('id','')
        if not re.fullmatch(r'[A-Za-z0-9_-]+',key) or index.name!=key+'.json':
            raise ValueError('课堂标识与索引不匹配')
        bundle=(self.root/note['_bundle']).resolve() if note.get('_bundle') else None
        if bundle is not None:
            bundles=(self.root/'课堂资料').resolve()
            if bundle.parent.parent!=bundles or not bundle.is_relative_to(bundles):
                raise ValueError('课堂路径不在资料目录内')
            if bundle.exists():
                owned=json.loads((bundle/'课堂笔记.json').read_text('utf8'))
                if owned.get('id')!=key:raise ValueError('课堂目录与索引不匹配')
        trash=(self.root/'已删除课堂').resolve()
        if trash.parent!=self.root:raise ValueError('已删除课堂目录无效')
        target=trash/(key+'_'+uuid.uuid4().hex[:8])
        target.mkdir(parents=True)
        moved=False
        try:
            write_json(target/'删除记录.json',{'id':key,'title':note.get('title',''),
                                           'original_bundle':note.get('_bundle','')})
            if bundle is not None and bundle.exists():
                bundle.rename(target/'课堂资料');moved=True
            index.rename(target/'课堂索引.json')
        except Exception:
            if moved:(target/'课堂资料').rename(bundle)
            raise
        return target

    def persist(self,note):
        if not re.fullmatch(r'[A-Za-z0-9_-]+',note['id']):raise ValueError('课堂标识无效')
        target=self.subject_path(note.get('subject',''))/(safe_name(note['title'])+'__'+safe_name(note['id'])[:8])
        old=(self.root/note['_bundle']).resolve() if note.get('_bundle') else None
        if old is not None and not old.is_relative_to(self.root/'课堂资料'):
            raise ValueError('课堂路径不在资料目录内')
        audio=Path(note.get('audio',''))
        inside=old is not None and audio.is_absolute() and audio.resolve().is_relative_to(old)
        if old and old!=target and old.is_dir():
            # Both paths are verified within this data root; rename the whole
            # bundle so user-added attachments move with the classroom too.
            if target.exists():raise FileExistsError('目标课堂目录已存在：'+str(target))
            old.rename(target)
            try:old.parent.rmdir()
            except OSError:pass
            if inside:audio=target/audio.resolve().relative_to(old)
        target.mkdir(parents=True,exist_ok=True)
        if audio.is_file() and not audio.resolve().is_relative_to(target):
            copied=target/audio.name
            if copied.exists():copied=target/('录音_'+audio.name)
            staging=copied.with_suffix(copied.suffix+'.copying')
            shutil.copy2(audio,staging);staging.replace(copied);audio=copied
        note['audio']=str(audio);note['_bundle']=str(target.relative_to(self.root))
        for key,name in [('transcript','转写原文.txt'),('summary','课堂摘录.txt'),('ai_summary','AI总结.md'),('notes','我的笔记.txt')]:
            path=target/name;tmp=path.with_suffix('.tmp');tmp.write_text(note.get(key,''),'utf8');tmp.replace(path)
        write_json(target/'课堂笔记.json',note)
        write_json(self.root/(note['id']+'.json'),note)
        return target
