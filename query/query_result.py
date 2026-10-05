from dataclasses import dataclass,field
from typing import Any,Dict,List,Optional,Sequence,Union
@dataclass
class QueryResult:
    success:bool;statement:str;columns:List[str]=field(default_factory=list);rows:List[Dict[str,Any]]=field(default_factory=list);affected_rows:int=0;execution_time_ms:float=0.0;execution_plan:Optional[Dict[str,Any]]=None;error:Optional[str]=None
    @classmethod
    def ok(cls,statement,*,columns=(),rows=(),affected_rows=0,execution_time_ms=0.0,execution_plan=None):return cls(True,statement,list(columns),[dict(r) for r in rows],affected_rows,execution_time_ms,execution_plan,None)
    @classmethod
    def fail(cls,statement,error,*,execution_time_ms=0.0):return cls(False,statement,execution_time_ms=execution_time_ms,error=str(error))
    def to_dict(self):return {"success":self.success,"statement":self.statement,"columns":self.columns,"rows":self.rows,"affected_rows":self.affected_rows,"execution_time_ms":self.execution_time_ms,"execution_plan":self.execution_plan,"error":self.error}
