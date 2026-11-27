// Public local-test helpers; no production browser or CDP connection.
module.exports={...require('./tests/browser_runtime.cjs'),...require('./tests/workbench_browser_access.cjs')};
