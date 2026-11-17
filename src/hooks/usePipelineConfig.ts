import { useCallback, useEffect, useState } from 'react';
import {
  DEFAULT_PIPELINE_CONFIG,
  loadPipelineConfig,
  savePipelineConfig,
  sanitizeConfig,
} from '../core/pipelineConfig';
import type { AutomationConfig, PipelineConfig } from '../types/pipeline';

type Setter = PipelineConfig | ((prev: PipelineConfig) => PipelineConfig);

/**
 * 全应用唯一的配置状态源：仿真参数与真机自动化参数合并为一份，
 * 每次变更即时写入 localStorage；读取时统一走 sanitizeConfig 清洗。
 */
export function usePipelineConfig() {
  const [config, setConfigState] = useState<PipelineConfig>(() => loadPipelineConfig());

  useEffect(() => {
    savePipelineConfig(config);
  }, [config]);

  const setConfig = useCallback((next: Setter) => {
    setConfigState((prev) => sanitizeConfig(typeof next === 'function' ? next(prev) : next));
  }, []);

  const patchAutomation = useCallback((patch: Partial<AutomationConfig>) => {
    setConfigState((prev) => sanitizeConfig({ ...prev, ...patch }));
  }, []);

  const resetConfig = useCallback(() => {
    setConfigState(sanitizeConfig(DEFAULT_PIPELINE_CONFIG));
  }, []);

  return { config, setConfig, patchAutomation, resetConfig };
}
