"""
ReAct Orchestrator Node

基于Function Calling的ReAct主控制器节点，采用模块化设计。
负责处理单次ReAct推理和决策逻辑。
"""

import time
from typing import Dict, List, Any
from pocketflow import AsyncNode

# 导入OpenAI SDK和Function Calling工具
from utils.openai_client import get_openai_client
from agent.function_calling import get_agent_function_definitions

# 导入重构后的组件
from .constants import (
    StateKeys, ErrorMessages,
    DefaultValues
)
from .message_builder import MessageBuilder
from .tool_executor import ToolExecutor
from .state_manager import StateManager
from .stream_handler import StreamHandler


class ReActOrchestratorNode(AsyncNode):
    """ReAct主控制器节点 - 模块化设计"""

    def __init__(self):
        super().__init__()
        self.name = "ReActOrchestratorNode"
        self.description = "基于Function Calling的模块化ReAct主控制器节点"

        # 初始化OpenAI客户端
        self.openai_client = get_openai_client()

        # 获取可用的Function Calling工具
        self.available_tools = get_agent_function_definitions()

        # 初始化组件
        self.message_builder = MessageBuilder()
        self.tool_executor = ToolExecutor()
        self.state_manager = StateManager()
        self.stream_handler = StreamHandler(self.available_tools, self.tool_executor)

        # 性能统计
        self.performance_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "total_tool_calls": 0
        }

    async def prep_async(self, shared: Dict[str, Any]) -> Dict[str, Any]:
        """异步准备ReAct执行环境"""
        try:
            # 获取最新用户消息
            user_message = self.state_manager.get_user_message_from_history(shared)

            # 获取当前状态
            current_stage = shared.get(StateKeys.CURRENT_STAGE, DefaultValues.DEFAULT_STAGE)

            # 构建状态描述
            state_info = self.state_manager.build_state_description(shared, user_message)

            return {
                "success": True,
                "user_message": user_message,
                "current_stage": current_stage,
                "state_info": state_info,
                "shared_data": shared
            }

        except Exception as e:
            return {"error": f"{ErrorMessages.REACT_PREP_FAILED}: {str(e)}"}

    async def exec_async(self, prep_result: Dict[str, Any]) -> Dict[str, Any]:
        """异步ReAct推理和决策逻辑 - 基于Function Calling"""
        start_time = time.time()
        self.performance_stats["total_requests"] += 1
        
        try:
            if "error" in prep_result:
                raise ValueError(prep_result["error"])

            user_message = prep_result["user_message"]
            state_info = prep_result["state_info"]
            shared_data = prep_result.get("shared_data", {})

            # 构建对话消息（使用增强版本，包含工具执行历史）
            messages = self.message_builder.build_enhanced_conversation_messages(
                user_message, state_info, shared_data
            )

            # 检查是否有流式回调
            stream_callback = shared_data.get(StateKeys.STREAM_CALLBACK)

            if stream_callback:
                # 使用流式Function Calling
                result = await self.stream_handler.execute_with_function_calling_stream(
                    messages, stream_callback, shared_data
                )
            else:
                # 使用标准Function Calling
                result = await self._execute_with_function_calling(messages, shared_data)

            # 更新性能统计
            self.performance_stats["successful_requests"] += 1
            self.performance_stats["total_tool_calls"] += len(result.get("tool_calls", []))
            
            response_time = time.time() - start_time
            self._update_average_response_time(response_time)

            return result

        except Exception as e:
            print(f"❌ ReAct执行失败: {e}")
            self.performance_stats["failed_requests"] += 1
            
            return {
                "error": f"{ErrorMessages.REACT_EXEC_FAILED}: {str(e)}",
                "user_message": ErrorMessages.GENERIC_ERROR,
                "decision_success": False
            }

    async def post_async(
        self,
        shared: Dict[str, Any],
        prep_res: Dict[str, Any],
        exec_res: Dict[str, Any]
    ) -> str:
        """异步更新共享状态 - 新架构：通过统一消息管理层"""
        try:
            if "error" in exec_res:
                shared["react_error"] = exec_res["error"]
                return "error"

            # 更新ReAct循环计数
            self.state_manager.increment_react_cycle(shared)

            # 🔧 新架构：Agent层将结果传递给统一消息管理层
            assistant_message = exec_res.get("user_message", "")
            tool_calls = exec_res.get("tool_calls", [])

            # 如果有助手消息或工具调用，都需要添加到统一管理层
            if assistant_message or tool_calls:
                # 通过统一消息管理层添加助手回复
                from core.unified_context import get_context
                context = get_context()
                
                # 如果没有文本回复但有工具调用，生成一个总结性回复
                if not assistant_message and tool_calls:
                    successful_tools = [tc.get("tool_name") for tc in tool_calls if tc.get("success")]
                    if successful_tools:
                        assistant_message = f"我已经为您执行了以下操作：{', '.join(successful_tools)}。请查看结果。"
                    else:
                        assistant_message = "我尝试执行了一些操作，但遇到了问题。"
                
                context.add_assistant_message(assistant_message, tool_calls)
                
                # 记录工具执行到统一管理层
                for tool_call in tool_calls:
                    if tool_call.get("success"):
                        context.record_tool_execution(
                            tool_name=tool_call.get("tool_name", ""),
                            arguments=tool_call.get("arguments", {}),
                            result=tool_call.get("result", {}),
                            execution_time=tool_call.get("execution_time")
                        )

            # 处理工具调用结果（更新shared状态）
            if tool_calls:
                for tool_call in tool_calls:
                    tool_name = tool_call.get("tool_name")
                    tool_result = tool_call.get("result")
                    tool_args = tool_call.get("arguments", {})
                    execution_time = tool_call.get("execution_time")

                    # 记录工具执行历史到shared（向后兼容）
                    if tool_name and tool_result:
                        self.state_manager.record_tool_execution(
                            shared, tool_name, tool_args, tool_result, execution_time
                        )

                    # 更新共享状态（仅成功的工具调用）
                    if tool_name and tool_result and tool_result.get("success"):
                        self.state_manager.update_shared_state_with_tool_result(
                            shared, tool_name, tool_result
                        )

            # 简化路由：总是等待用户，让LLM在回复中自然引导下一步
            return "wait_for_user"

        except Exception as e:
            print(f"❌ ReAct post处理失败: {e}")
            shared["react_post_error"] = str(e)
            return "error"

    async def _execute_with_function_calling(
        self, 
        messages: List[Dict[str, str]], 
        shared_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """使用Function Calling执行ReAct逻辑 - 支持混合模式"""
        try:
            # 启用并行工具调用
            response = await self.openai_client.chat_completion_async(
                messages=messages,
                tools=self.available_tools,
                tool_choice="auto",
                parallel_tool_calls=True
            )

            # 处理响应
            choice = response.choices[0]
            message = choice.message
            
            # 提取助手回复
            assistant_message = message.content or ""

            # 处理工具调用（支持多个并行调用）
            tool_calls = []

            # 检查标准的OpenAI Function Calling格式
            if message.tool_calls:
                tool_calls = await self.tool_executor.execute_tools_parallel(message.tool_calls)

            # 如果没有标准格式的工具调用，检查自定义格式
            elif assistant_message and "<tool_call>" in assistant_message:
                print("🔧 检测到自定义格式的工具调用")
                custom_tool_calls = self.tool_executor.parse_custom_tool_calls(assistant_message)
                
                if custom_tool_calls:
                    tool_calls = await self.tool_executor.execute_custom_tool_calls(custom_tool_calls)
                    # 清理assistant_message中的工具调用标记
                    assistant_message = self.tool_executor.clean_tool_call_markers(assistant_message)

            # LLM已经通过Function Calling做出了决策，我们只需要处理结果
            return {
                "user_message": assistant_message,
                "tool_calls": tool_calls,
                "reasoning": self._build_simple_reasoning(tool_calls, assistant_message),
                "confidence": DefaultValues.DEFAULT_CONFIDENCE,
                "decision_success": True,
                "execution_mode": "parallel" if len(tool_calls) > 1 else "single"
            }

        except Exception as e:
            print(f"❌ Function Calling执行失败: {e}")
            return {
                "error": f"{ErrorMessages.FUNCTION_CALLING_FAILED}: {str(e)}",
                "user_message": ErrorMessages.GENERIC_ERROR,
                "decision_success": False
            }

    def _build_simple_reasoning(
        self,
        tool_calls: List[Dict[str, Any]],
        assistant_message: str
    ) -> str:
        """
        构建简单的推理说明（替代DecisionEngine）

        Args:
            tool_calls: 工具调用结果列表
            assistant_message: 助手消息

        Returns:
            推理说明字符串
        """
        if not tool_calls:
            return "LLM选择进行对话交互，未调用工具"

        successful_tools = [tc["tool_name"] for tc in tool_calls if tc.get("success", False)]
        failed_tools = [tc["tool_name"] for tc in tool_calls if not tc.get("success", False)]

        reasoning_parts = [f"LLM决策执行了 {len(tool_calls)} 个工具调用"]

        if successful_tools:
            reasoning_parts.append(f"成功: {', '.join(successful_tools)}")
        if failed_tools:
            reasoning_parts.append(f"失败: {', '.join(failed_tools)}")

        return "; ".join(reasoning_parts)

    def _update_average_response_time(self, response_time: float) -> None:
        """更新平均响应时间"""
        total_requests = self.performance_stats["total_requests"]
        current_avg = self.performance_stats["average_response_time"]
        
        # 计算新的平均值
        new_avg = ((current_avg * (total_requests - 1)) + response_time) / total_requests
        self.performance_stats["average_response_time"] = new_avg

    def get_performance_stats(self) -> Dict[str, Any]:
        """获取性能统计信息"""
        stats = self.performance_stats.copy()
        stats.update({
            "tool_executor_stats": self.tool_executor.get_execution_stats()
        })
        return stats

    def reset_stats(self) -> None:
        """重置所有统计信息"""
        self.performance_stats = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "average_response_time": 0.0,
            "total_tool_calls": 0
        }
        self.tool_executor.reset_execution_stats()
