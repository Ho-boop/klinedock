"""
KlineDock - 数据格式转换器

将币安数据转换为LEAN引擎格式以及其他格式转换
"""

import io
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional, List
import pandas as pd
from loguru import logger

from src.core.config import get_config


class DataConverter:
    """
    数据格式转换器
    
    支持:
    - 币安K线 → LEAN ZIP格式
    - LEAN ZIP → DataFrame
    - 通用CSV格式转换
    """
    
    def __init__(self, output_dir: Optional[Path] = None):
        """
        初始化转换器
        
        Args:
            output_dir: 输出目录，默认使用配置的lean_data目录
        """
        config = get_config()
        self.output_dir = output_dir or (config.data_dir / "lean_data")
        self.output_dir.mkdir(parents=True, exist_ok=True)
    
    def binance_to_lean(
        self,
        df: pd.DataFrame,
        symbol: str,
        resolution: str = "minute"
    ) -> List[Path]:
        """
        将币安K线数据转换为LEAN格式
        
        LEAN格式说明:
        - 路径: {symbol}/minute/{yyyymmdd}_trade.zip
        - ZIP内容: CSV文件，无表头
        - 列: Time(ms), Open, High, Low, Close, Volume
        
        Args:
            df: 币安K线DataFrame（需有datetime索引）
            symbol: 交易对，如 'BTCUSDT'
            resolution: 分辨率 ('minute', 'hour', 'daily')
            
        Returns:
            List[Path]: 生成的文件路径列表
        """
        if df.empty:
            logger.warning("输入数据为空，跳过转换")
            return []
        
        # 确保索引是datetime类型
        if not isinstance(df.index, pd.DatetimeIndex):
            if "datetime" in df.columns:
                df.set_index("datetime", inplace=True)
            elif "open_time" in df.columns:
                df.set_index("open_time", inplace=True)
            else:
                raise ValueError("DataFrame必须有datetime索引或datetime/open_time列")
        
        # 创建输出目录
        symbol_lower = symbol.lower()
        symbol_dir = self.output_dir / symbol_lower / resolution
        symbol_dir.mkdir(parents=True, exist_ok=True)
        
        # 按日期分组
        df["date"] = df.index.date
        grouped = df.groupby("date")
        
        output_files = []
        
        for date, group in grouped:
            # 格式化日期
            date_str = date.strftime("%Y%m%d")
            zip_path = symbol_dir / f"{date_str}_trade.zip"
            
            # 准备LEAN格式数据
            lean_df = pd.DataFrame()
            
            # LEAN使用毫秒时间戳（相对于当天开始的偏移）
            day_start = pd.Timestamp(date)
            lean_df["time"] = ((group.index - day_start).total_seconds() * 1000).astype(int)
            lean_df["open"] = group["open"]
            lean_df["high"] = group["high"]
            lean_df["low"] = group["low"]
            lean_df["close"] = group["close"]
            lean_df["volume"] = group["volume"]
            
            # 转换为CSV字符串（无表头）
            csv_content = lean_df.to_csv(index=False, header=False)
            
            # 写入ZIP文件
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(f"{date_str}_trade.csv", csv_content)
            
            output_files.append(zip_path)
            logger.debug(f"已生成: {zip_path}")
        
        logger.info(f"转换完成: {symbol} -> {len(output_files)} 个文件")
        return output_files
    
    def lean_to_dataframe(
        self,
        symbol: str,
        resolution: str = "minute",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        从LEAN格式读取数据为DataFrame
        
        Args:
            symbol: 交易对
            resolution: 分辨率
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            pd.DataFrame: OHLCV数据
        """
        symbol_lower = symbol.lower()
        data_dir = self.output_dir / symbol_lower / resolution
        
        if not data_dir.exists():
            logger.warning(f"数据目录不存在: {data_dir}")
            return pd.DataFrame()
        
        all_data = []
        
        # 遍历所有ZIP文件
        for zip_path in sorted(data_dir.glob("*_trade.zip")):
            # 解析日期
            date_str = zip_path.stem.replace("_trade", "")
            file_date = datetime.strptime(date_str, "%Y%m%d").date()
            
            # 日期过滤
            if start_date and file_date < start_date.date():
                continue
            if end_date and file_date > end_date.date():
                continue
            
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    # 获取CSV文件名
                    csv_name = zf.namelist()[0]
                    
                    with zf.open(csv_name) as f:
                        # 读取CSV
                        df = pd.read_csv(
                            f,
                            names=["time", "open", "high", "low", "close", "volume"]
                        )
                        
                        # 恢复datetime
                        day_start = pd.Timestamp(file_date)
                        df["datetime"] = day_start + pd.to_timedelta(df["time"], unit="ms")
                        df.drop(columns=["time"], inplace=True)
                        
                        all_data.append(df)
                        
            except Exception as e:
                logger.error(f"读取文件失败 {zip_path}: {e}")
                continue
        
        if not all_data:
            return pd.DataFrame()
        
        # 合并所有数据
        result = pd.concat(all_data, ignore_index=True)
        result.set_index("datetime", inplace=True)
        result.sort_index(inplace=True)
        
        logger.info(f"从LEAN格式读取 {len(result)} 条 {symbol} 数据")
        return result
    
    def to_csv(
        self,
        df: pd.DataFrame,
        filepath: Path,
        include_index: bool = True
    ) -> Path:
        """
        导出为CSV格式
        
        Args:
            df: 数据
            filepath: 输出路径
            include_index: 是否包含索引
            
        Returns:
            Path: 输出文件路径
        """
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        df.to_csv(filepath, index=include_index)
        logger.info(f"已导出CSV: {filepath}")
        
        return filepath
    
    def from_csv(
        self,
        filepath: Path,
        datetime_column: str = "datetime",
        parse_dates: bool = True
    ) -> pd.DataFrame:
        """
        从CSV读取数据
        
        Args:
            filepath: CSV文件路径
            datetime_column: 日期时间列名
            parse_dates: 是否解析日期
            
        Returns:
            pd.DataFrame: 数据
        """
        filepath = Path(filepath)
        
        if not filepath.exists():
            raise FileNotFoundError(f"文件不存在: {filepath}")
        
        if parse_dates:
            df = pd.read_csv(filepath, parse_dates=[datetime_column], index_col=datetime_column)
        else:
            df = pd.read_csv(filepath)
            if datetime_column in df.columns:
                df.set_index(datetime_column, inplace=True)
        
        return df


class DataQualityChecker:
    """
    数据质量检查器
    
    检查项:
    - 时间戳连续性
    - 价格跳变异常
    - OHLC逻辑校验
    - 成交量异常
    """
    
    def __init__(
        self,
        max_price_change_pct: float = 0.1,
        max_volume_spike_ratio: float = 10.0
    ):
        """
        初始化检查器
        
        Args:
            max_price_change_pct: 单K线最大价格变化比例
            max_volume_spike_ratio: 最大成交量突增倍数
        """
        self.max_price_change_pct = max_price_change_pct
        self.max_volume_spike_ratio = max_volume_spike_ratio
    
    def check(self, df: pd.DataFrame) -> "DataQualityReport":
        """
        执行数据质量检查
        
        Args:
            df: OHLCV数据
            
        Returns:
            DataQualityReport: 检查报告
        """
        issues = []
        
        if df.empty:
            return DataQualityReport(
                total_rows=0,
                issues=[DataQualityIssue("empty", "数据为空", 0, 0)],
                quality_score=0.0
            )
        
        total_rows = len(df)
        
        # 1. OHLC逻辑检查
        ohlc_issues = self._check_ohlc_logic(df)
        issues.extend(ohlc_issues)
        
        # 2. 价格跳变检查
        price_issues = self._check_price_changes(df)
        issues.extend(price_issues)
        
        # 3. 成交量异常检查
        volume_issues = self._check_volume_spikes(df)
        issues.extend(volume_issues)
        
        # 4. 时间戳连续性检查
        time_issues = self._check_timestamp_continuity(df)
        issues.extend(time_issues)
        
        # 计算质量分数
        issue_count = len(issues)
        quality_score = max(0.0, 1.0 - (issue_count / total_rows))
        
        return DataQualityReport(
            total_rows=total_rows,
            issues=issues,
            quality_score=quality_score
        )
    
    def _check_ohlc_logic(self, df: pd.DataFrame) -> List["DataQualityIssue"]:
        """检查OHLC逻辑：High >= max(Open,Close), Low <= min(Open,Close)"""
        issues = []
        
        # High应该是最高价
        invalid_high = df[df["high"] < df[["open", "close"]].max(axis=1)]
        for idx in invalid_high.index:
            issues.append(DataQualityIssue(
                issue_type="ohlc_logic",
                description=f"High < max(Open,Close)",
                row_index=df.index.get_loc(idx),
                timestamp=idx
            ))
        
        # Low应该是最低价
        invalid_low = df[df["low"] > df[["open", "close"]].min(axis=1)]
        for idx in invalid_low.index:
            issues.append(DataQualityIssue(
                issue_type="ohlc_logic",
                description=f"Low > min(Open,Close)",
                row_index=df.index.get_loc(idx),
                timestamp=idx
            ))
        
        return issues
    
    def _check_price_changes(self, df: pd.DataFrame) -> List["DataQualityIssue"]:
        """检查价格跳变"""
        issues = []
        
        price_change = df["close"].pct_change().abs()
        abnormal = price_change[price_change > self.max_price_change_pct]
        
        for idx in abnormal.index:
            issues.append(DataQualityIssue(
                issue_type="price_spike",
                description=f"价格变化 {abnormal[idx]:.2%} 超过阈值 {self.max_price_change_pct:.2%}",
                row_index=df.index.get_loc(idx),
                timestamp=idx
            ))
        
        return issues
    
    def _check_volume_spikes(self, df: pd.DataFrame) -> List["DataQualityIssue"]:
        """检查成交量异常"""
        issues = []
        
        volume_mean = df["volume"].rolling(window=20, min_periods=1).mean()
        volume_ratio = df["volume"] / volume_mean
        abnormal = volume_ratio[volume_ratio > self.max_volume_spike_ratio]
        
        for idx in abnormal.index:
            issues.append(DataQualityIssue(
                issue_type="volume_spike",
                description=f"成交量是均值的 {abnormal[idx]:.1f} 倍",
                row_index=df.index.get_loc(idx),
                timestamp=idx
            ))
        
        return issues
    
    def _check_timestamp_continuity(self, df: pd.DataFrame) -> List["DataQualityIssue"]:
        """检查时间戳连续性"""
        issues = []
        
        if not isinstance(df.index, pd.DatetimeIndex):
            return issues
        
        # 计算时间间隔
        time_diff = df.index.to_series().diff()
        
        if len(time_diff) < 2:
            return issues
        
        # 获取预期间隔（众数）
        expected_interval = time_diff.mode().iloc[0] if not time_diff.mode().empty else None
        
        if expected_interval is None:
            return issues
        
        # 找出间隔异常的点（允许2倍误差）
        abnormal = time_diff[time_diff > expected_interval * 2]
        
        for idx in abnormal.index:
            if pd.isna(abnormal[idx]):
                continue
            issues.append(DataQualityIssue(
                issue_type="time_gap",
                description=f"时间间隔 {abnormal[idx]} 异常（预期 {expected_interval}）",
                row_index=df.index.get_loc(idx),
                timestamp=idx
            ))
        
        return issues


class DataQualityIssue:
    """数据质量问题"""
    
    def __init__(
        self,
        issue_type: str,
        description: str,
        row_index: int,
        timestamp: datetime
    ):
        self.issue_type = issue_type
        self.description = description
        self.row_index = row_index
        self.timestamp = timestamp
    
    def __repr__(self):
        return f"<Issue {self.issue_type}: {self.description} @ {self.timestamp}>"


class DataQualityReport:
    """数据质量报告"""
    
    def __init__(
        self,
        total_rows: int,
        issues: List[DataQualityIssue],
        quality_score: float
    ):
        self.total_rows = total_rows
        self.issues = issues
        self.quality_score = quality_score
    
    @property
    def issue_count(self) -> int:
        return len(self.issues)
    
    @property
    def is_healthy(self) -> bool:
        return self.quality_score >= 0.95
    
    def summary(self) -> str:
        """生成摘要"""
        lines = [
            f"数据质量报告",
            f"=" * 30,
            f"总行数: {self.total_rows}",
            f"问题数: {self.issue_count}",
            f"质量分: {self.quality_score:.2%}",
            f"状态: {'✅ 健康' if self.is_healthy else '⚠️ 需关注'}"
        ]
        
        if self.issues:
            lines.append("\n问题分类:")
            issue_types = {}
            for issue in self.issues:
                issue_types[issue.issue_type] = issue_types.get(issue.issue_type, 0) + 1
            for t, count in issue_types.items():
                lines.append(f"  - {t}: {count}")
        
        return "\n".join(lines)
    
    def __repr__(self):
        return f"<DataQualityReport rows={self.total_rows} issues={self.issue_count} score={self.quality_score:.2%}>"
