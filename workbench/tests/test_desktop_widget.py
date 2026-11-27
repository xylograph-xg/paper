import json,tempfile,unittest
from core.api import paths__WorkspacePath as Path
from desktop_widget.snapshot import snapshot,command_files,upload_issue

class PanelWorkflow(unittest.TestCase):
 def test_nested_launchers_do_not_scan_environments_or_list_the_panel_itself(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   for relative in ('workbench/commands/启动文献工作台.command','workbench/commands/启动任务面板.command',
                    'infrastructure/environments/web/unused.command','infrastructure/cache/old.command',
                    'fetch/dependencies/unused.command'):
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
   self.assertEqual([r['relativePath'] for r in command_files(root)],['workbench/commands/启动文献工作台.command'])
 def test_current_commands_exclude_self_old_viewer_archives_and_pin_gpt_last(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td)
   for relative in ('启动文献工作台.command','启动任务面板.command','read/启动资料卡.command','read/配置阅读环境.command','article/open_gpt.command','article/run.command','archive/old.command','backups/old.command','data/workflow_versions/old/run.command','运行卡片评审.command'):
    p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('fixture')
   (root/'outside.command').symlink_to('/tmp/other.command')
   commands=command_files(root)
   self.assertEqual([c['relativePath'] for c in commands],['启动文献工作台.command','article/open_gpt.command'])
 def test_fetch_and_web_cards_permanent_old_rounds_absent(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);p=root/'data/web_card_loops/test/loop.json';p.parent.mkdir(parents=True);p.write_text(json.dumps({'state':'running_round'}))
   value=snapshot(root);self.assertEqual({r['group'] for r in value['rows']},{'paper · 拉取','paper · 制卡'})
   self.assertFalse(any('三轮' in r['group'] for r in value['rows']));self.assertFalse((root/'data/catalog.sqlite3').exists())
 def test_level1_registered_status_shown_without_start_or_model_controls(self):
  import os,time
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir()
   status=data/'literature-level1-service.json'
   status.write_text(json.dumps({'pid':os.getpid(),'state':'waiting','updated':time.time(),
       'completed':8,'total':10,'matched':6,'undetermined':2,'queued':2,'actual_parallel':0}))
   before=status.read_bytes();value=snapshot(root)
   first=next(r for r in value['rows'] if r['group']=='paper · 一级标签')
   self.assertIn('8/10',first['detail']);self.assertIn('并行上限 8 / 当前 0',first['detail'])
   self.assertEqual(first['state'],'等待新增或更新')
   self.assertEqual(status.read_bytes(),before)
   self.assertFalse((data/'literature-level1-control.json').exists())
   self.assertFalse((data/'literature.sqlite3').exists())
 def test_level2_registered_status_shown_without_start_or_model_controls(self):
  import os,time
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir()
   status=data/'literature-level2-service.json'
   status.write_text(json.dumps({'pid':os.getpid(),'state':'waiting','updated':time.time(),
       'completed':8,'total':10,'matched':6,'undetermined':2,'queued':2,'actual_parallel':0}))
   before=status.read_bytes();value=snapshot(root)
   first=next(r for r in value['rows'] if r['group']=='paper · 二级标签')
   self.assertIn('8/10',first['detail']);self.assertIn('并行上限 8 / 当前 0',first['detail'])
   self.assertEqual(first['state'],'等待新增或更新')
   self.assertEqual(status.read_bytes(),before)
   self.assertFalse((data/'literature-level2-control.json').exists())
   self.assertFalse((data/'literature.sqlite3').exists())
 def test_shared_question_status_does_not_start_or_rewrite_jobs(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);q=root/'question';folder=q/'studies/demo';folder.mkdir(parents=True)
   (folder/'study.json').write_text(json.dumps({'id':'demo','question':'shared research','status':'in_progress'}))
   (folder/'tasks.json').write_text(json.dumps([{'status':'completed'},{'status':'pending'}]))
   before=(folder/'study.json').read_bytes();value=snapshot(root,question_root=q)
   research=next(r for r in value['rows'] if r['group']=='question · 研究生成');self.assertIn('1/2',research['detail'])
   self.assertEqual((folder/'study.json').read_bytes(),before)
 def test_provider_warning_displays_backup_and_cooldown(self):
  import time
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir();(data/'web-provider-control.json').write_text(json.dumps({'chatgpt':{'blocked_until':time.time()+300,'reason':'quota'}}))
   value=snapshot(root);self.assertTrue(any('备用网页' in w for w in value['warnings']));self.assertIn('受限',upload_issue('too many files uploaded'))
 def test_review_shares_attachment_quota_wait_and_pause_takes_priority(self):
  import os,time
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as td:
   root=Path(td);data=root/'data';data.mkdir();(root/'config').mkdir()
   (root/'config/first_round.json').write_text(json.dumps({'card_review':{'enabled':True}}))
   (data/'web-card-service.json').write_text(json.dumps({'pid':os.getpid(),'state':'running'}))
   (data/'web-provider-control.json').write_text(json.dumps({'chatgpt':{'blocked_until':time.time()+300,'reason':'quota'}}))
   review={'enabled':True,'counts':{},'jobs':[],'last_finished_at':None}
   with patch('review.card_review_queue.status',return_value=review):
    value=snapshot(root)
    card=next(r for r in value['rows'] if r.get('concurrencyTarget')=='cards')
    check=next(r for r in value['rows'] if r.get('concurrencyTarget')=='review')
    self.assertEqual(check['state'],card['state']);self.assertEqual(check['state'],'等待附件额度恢复')
    self.assertEqual(check['issue'],'GPT附件额度受限');self.assertIn('上次结束',check['detail'])
    review['enabled']=False
    check=next(r for r in snapshot(root)['rows'] if r.get('concurrencyTarget')=='review')
    self.assertEqual(check['state'],'已暂停');self.assertEqual(check['issue'],'')
if __name__=='__main__':unittest.main()
