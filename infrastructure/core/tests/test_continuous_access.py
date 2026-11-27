from unittest.mock import patch
from workbench.tests.test_workbench_access import WorkbenchAccess

class ContinuousAccess(WorkbenchAccess):
 def test_continuous_start_requires_authentication_and_is_explicit(self):
  with patch('core.continuous_start.start',return_value={'test':{'ok':True}}) as start:
   self.assertEqual(self.request('/api/continuous/start',b'{}')[0],403)
   self.assertEqual(self.request('/api/state',headers={'X-Paper-Token':self.secret})[0],200)
   start.assert_not_called()
   result=self.request('/api/continuous/start',b'{}',{'X-Paper-Token':self.secret,'Origin':self.url})
   self.assertEqual(result[0],200)
   start.assert_called_once_with(self.config,open_browser=True)
