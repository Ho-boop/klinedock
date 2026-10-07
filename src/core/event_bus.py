"""
KlineDock - 事件总线

实现模块间的松耦合通信
"""

import asyncio
from typing import Dict, List, Callable, Any, Optional, Awaitable, Union
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from loguru import logger


class EventType(str, Enum):
    """事件类型枚举"""
    
    # 系统事件
    SYSTEM_STARTUP = "system.startup"
    SYSTEM_SHUTDOWN = "system.shutdown"
    
    # 数据事件
    MARKET_DATA = "data.market"           # 行情数据
    TRADE_DATA = "data.trade"             # 成交数据
    ORDERBOOK_DATA = "data.orderbook"     # 订单簿数据
    
    # 策略事件
    STRATEGY_SIGNAL = "strategy.signal"   # 策略信号
    STRATEGY_START = "strategy.start"
    STRATEGY_STOP = "strategy.stop"
    STRATEGY_ERROR = "strategy.error"
    
    # 订单事件
    ORDER_CREATED = "order.created"
    ORDER_SUBMITTED = "order.submitted"
    ORDER_FILLED = "order.filled"
    ORDER_CANCELLED = "order.cancelled"
    ORDER_REJECTED = "order.rejected"
    
    # 持仓事件
    POSITION_OPENED = "position.opened"
    POSITION_CLOSED = "position.closed"
    POSITION_UPDATED = "position.updated"
    
    # 风控事件
    RISK_WARNING = "risk.warning"
    RISK_BREACH = "risk.breach"
    RISK_KILL_SWITCH = "risk.kill_switch"
    
    # 通知事件
    NOTIFICATION = "notification"


@dataclass
class Event:
    """事件对象"""
    event_type: EventType
    data: Dict[str, Any] = field(default_factory=dict)
    source: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    event_id: str = ""
    
    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"{self.event_type.value}_{self.timestamp.timestamp()}"


# 事件处理器类型
EventHandler = Union[
    Callable[[Event], None],
    Callable[[Event], Awaitable[None]]
]


class EventBus:
    """事件总线"""
    
    def __init__(self):
        self._handlers: Dict[EventType, List[EventHandler]] = {}
        self._async_queue: Optional[asyncio.Queue] = None
        self._running = False
    
    def subscribe(
        self, 
        event_type: EventType, 
        handler: EventHandler
    ) -> None:
        """订阅事件"""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        
        if handler not in self._handlers[event_type]:
            self._handlers[event_type].append(handler)
            logger.debug(f"订阅事件: {event_type.value} -> {handler.__name__}")
    
    def unsubscribe(
        self, 
        event_type: EventType, 
        handler: EventHandler
    ) -> None:
        """取消订阅"""
        if event_type in self._handlers:
            if handler in self._handlers[event_type]:
                self._handlers[event_type].remove(handler)
                logger.debug(f"取消订阅: {event_type.value} -> {handler.__name__}")
    
    def publish(self, event: Event) -> None:
        """发布事件（同步）"""
        handlers = self._handlers.get(event.event_type, [])
        
        for handler in handlers:
            try:
                result = handler(event)
                # 如果是协程，放入队列异步处理
                if asyncio.iscoroutine(result):
                    if self._async_queue:
                        self._async_queue.put_nowait((handler, event))
                    else:
                        # 没有事件循环时直接运行
                        asyncio.get_event_loop().run_until_complete(result)
            except Exception as e:
                logger.error(f"事件处理失败 {event.event_type.value}: {e}")
    
    async def publish_async(self, event: Event) -> None:
        """发布事件（异步）"""
        handlers = self._handlers.get(event.event_type, [])
        
        tasks = []
        for handler in handlers:
            try:
                result = handler(event)
                if asyncio.iscoroutine(result):
                    tasks.append(result)
            except Exception as e:
                logger.error(f"事件处理失败 {event.event_type.value}: {e}")
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    async def start(self) -> None:
        """启动事件总线"""
        self._running = True
        self._async_queue = asyncio.Queue()
        logger.info("事件总线已启动")
        
        # 发布启动事件
        await self.publish_async(Event(
            event_type=EventType.SYSTEM_STARTUP,
            source="event_bus"
        ))
    
    async def stop(self) -> None:
        """停止事件总线"""
        # 发布关闭事件
        await self.publish_async(Event(
            event_type=EventType.SYSTEM_SHUTDOWN,
            source="event_bus"
        ))
        
        self._running = False
        self._async_queue = None
        logger.info("事件总线已停止")
    
    def clear(self) -> None:
        """清除所有订阅"""
        self._handlers.clear()


# 全局事件总线实例
event_bus = EventBus()


# 便捷装饰器
def on_event(event_type: EventType):
    """事件订阅装饰器"""
    def decorator(func: EventHandler):
        event_bus.subscribe(event_type, func)
        return func
    return decorator
