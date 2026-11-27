const {createRequire}=require('module');
let runtime;try{runtime=require('playwright');}catch(error){
 if(!process.env.PAPER_TEST_NODE_MODULE_ROOT)throw Error('Install playwright or set PAPER_TEST_NODE_MODULE_ROOT to the bundled node package.json');
 runtime=createRequire(process.env.PAPER_TEST_NODE_MODULE_ROOT)('playwright');}
module.exports=runtime;
