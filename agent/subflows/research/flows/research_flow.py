"""
研究调研流程 - 完全重构版本
完全模仿官方示例的并发实现方式
"""

import asyncio
import os
from typing import Dict, List, Any
from pocketflow_tracing import trace_flow
from pocketflow import AsyncFlow, AsyncNode
from .keyword_research_flow import create_keyword_research_subflow


class ConcurrentResearchNode(AsyncNode):
    """并发研究节点 - 在ResearchFlow内部处理并发"""

    def __init__(self):
        super().__init__()
        self.name = "concurrent_research"
        self._subflows_and_data = []
        self._execution_results = []

    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """准备并发研究参数"""

        # 获取研究参数
        research_keywords = shared.get("research_keywords", [])
        focus_areas = shared.get("focus_areas", [])
        project_context = shared.get("project_context", "")


        # 创建子流程和数据对
        subflows_and_data = []
        for keyword in research_keywords:
            keyword_subflow = create_keyword_research_subflow()
            keyword_data = {
                "current_keyword": keyword,
                "focus_areas": focus_areas,
                "project_context": project_context
            }
            subflows_and_data.append((keyword_subflow, keyword_data))

        # 存储到实例变量
        self._subflows_and_data = subflows_and_data

        return {
            "keywords": research_keywords,
            "focus_areas": focus_areas,
            "project_context": project_context,
            "total_keywords": len(research_keywords),
            "execution_start_time": asyncio.get_event_loop().time()
        }

    async def exec_async(self, prep_res: Dict[str, Any]) -> Dict[str, Any]:
        """并发执行关键词研究"""

        subflows_and_data = self._subflows_and_data
        keywords = prep_res["keywords"]

        print(f"🚀 开始并发执行 {len(subflows_and_data)} 个关键词研究...")
        start_time = asyncio.get_event_loop().time()

        # 🔧 关键：在节点内部并发执行所有子流程
        results = await asyncio.gather(*[
            subflow.run_async(data)
            for subflow, data in subflows_and_data
        ], return_exceptions=True)

        execution_time = asyncio.get_event_loop().time() - start_time

        # 分析结果
        successful_results = []
        failed_results = []

        for result, (_, data) in zip(results, subflows_and_data):
            keyword = data["current_keyword"]

            if isinstance(result, Exception):
                print(f"⚠️ 关键词 '{keyword}' 处理失败: {result}")
                failed_results.append({
                    "keyword": keyword,
                    "error": str(result)
                })
            else:
                keyword_result = data.get("keyword_result", {})
                successful_results.append({
                    "keyword": keyword,
                    "result": keyword_result
                })

        successful_count = len(successful_results)
        failed_count = len(failed_results)


        # 存储结果到实例变量
        self._execution_results = {
            "successful_results": successful_results,
            "failed_results": failed_results
        }

        return {
            "execution_time": execution_time,
            "statistics": {
                "total": len(keywords),
                "successful": successful_count,
                "failed": failed_count
            },
            "success_rate": successful_count / len(keywords) if keywords else 0
        }

    async def post_async(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> str:
        """处理并发研究结果"""

        statistics = exec_res["statistics"]
        success_rate = exec_res["success_rate"]

        # 从实例变量获取详细结果
        execution_results = self._execution_results
        successful_results = execution_results["successful_results"]
        failed_results = execution_results["failed_results"]

        # 构建最终的研究结果
        keyword_results = []

        # 添加成功的结果
        for item in successful_results:
            keyword_results.append({
                "keyword": item["keyword"],
                "success": True,
                "result": item["result"]
            })

        # 添加失败的结果
        for item in failed_results:
            keyword_results.append({
                "keyword": item["keyword"],
                "success": False,
                "error": item["error"]
            })

        # 生成研究摘要
        summary = self._generate_summary(
            prep_res["keywords"],
            prep_res["focus_areas"],
            statistics["successful"],
            statistics["total"]
        )

        # 构建最终的research_findings
        research_findings = {
            "project_context": prep_res["project_context"],
            "research_keywords": prep_res["keywords"],
            "focus_areas": prep_res["focus_areas"],
            "total_keywords": statistics["total"],
            "successful_keywords": statistics["successful"],
            "failed_keywords": statistics["failed"],
            "keyword_results": keyword_results,
            "summary": summary,
            "execution_time": exec_res["execution_time"],
            "success_rate": success_rate
        }

        # 保存到shared状态
        shared["research_findings"] = research_findings

        return "research_complete"

    def _generate_summary(self, keywords: List[str], focus_areas: List[str], successful: int, total: int) -> str:
        """生成研究摘要"""

        if successful == 0:
            return "研究过程中未能获得有效结果。"

        summary_parts = [
            f"针对 {total} 个关键词进行了技术调研",
            f"成功处理了 {successful} 个关键词",
            f"主要关注点包括: {', '.join(focus_areas)}"
        ]

        return "。".join(summary_parts) + "。"


@trace_flow(flow_name="ResearchFlow")
class TracedResearchFlow(AsyncFlow):
    """带tracing的研究调研流程"""

    def __init__(self):
        super().__init__()
        # 设置并发研究节点作为起始节点
        self.start_node = ConcurrentResearchNode()

    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """流程级准备"""
        shared["flow_start_time"] = asyncio.get_event_loop().time()

        return {
            "flow_start_time": shared["flow_start_time"],
            "operation": "research_flow"
        }

    async def post_async(self, shared: Dict[str, Any], prep_res: Dict[str, Any], exec_res: Dict[str, Any]) -> Dict[str, Any]:
        """流程级后处理"""
        flow_duration = asyncio.get_event_loop().time() - prep_res["flow_start_time"]
        print(f"✅ 研究调研流程完成，耗时: {flow_duration:.2f}秒")
        return exec_res


class ResearchFlow:
    """研究调研流程 - 使用带tracing的流程和并发节点"""

    def __init__(self):
        self.flow = TracedResearchFlow()

    async def run_async(self, shared: Dict[str, Any]) -> bool:
        """
        异步运行研究调研流程

        Args:
            shared: 共享状态字典，包含research_keywords, focus_areas, project_context

        Returns:
            bool: 执行是否成功
        """
        try:
            # 验证参数
            research_keywords = shared.get("research_keywords", [])
            focus_areas = shared.get("focus_areas", [])
            project_context = shared.get("project_context", "")

            if not research_keywords:
                print("❌ 缺少研究关键词")
                shared["research_error"] = "缺少研究关键词"
                return False

            if not focus_areas:
                print("❌ 缺少关注点")
                shared["research_error"] = "缺少关注点"
                return False


            # 🔧 使用带tracing的流程执行
            result = await self.flow.run_async(shared)

            if result and shared.get("research_findings"):
                print(f"✅ 研究调研流程完成，处理了 {len(research_keywords)} 个关键词")
                return True
            else:
                print("❌ 研究调研流程未能产生有效结果")
                return False

        except Exception as e:
            print(f"❌ 研究调研流程失败: {e}")
            shared["research_error"] = str(e)
            return False


def create_research_flow():
    """创建研究调研流程实例"""
    return ResearchFlow()
