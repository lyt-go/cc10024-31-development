<template>
  <div class="app-shell">
    <aside class="app-side">
      <h1 class="app-title">网页行为采集与内容清洗平台</h1>
      <nav class="nav-list">
        <RouterLink v-for="item in navItems" :key="item.path" :to="item.path" class="nav-item">
          {{ item.label }}
        </RouterLink>
      </nav>
    </aside>
    <main class="app-main">
      <header class="app-head">
        <span class="head-desc">面向网页行为录制、脚本化采集、内容清洗与结构化输出的数据采集与加工平台。</span>
        <span class="head-user">当前值班：数据工程组</span>
      </header>
      <RouterView />
    </main>
  </div>
</template>

<script setup lang="ts">
const navItems = [{ label: "运营概览", path: "/" }, { label: "行为脚本", path: "/behavior_script" }, { label: "元素定位", path: "/element_selector" }, { label: "数据抽取", path: "/data_extract" }, { label: "抽取适用集", path: "/extract_scope" }, { label: "清洗管道", path: "/clean_pipeline" }, { label: "转换规则", path: "/transform_rule" }, { label: "质量防护", path: "/quality_guard" }, { label: "脚本调度", path: "/script_schedule" }, { label: "登录凭证", path: "/login_mgr" }, { label: "页面快照", path: "/page_snapshot" }, { label: "错误恢复", path: "/error_recover" }, { label: "页面去重", path: "/page_dedup" }, { label: "字段归一化", path: "/field_normalize" }, { label: "批次队列", path: "/batch_queue" }, { label: "画布配置", path: "/canvas_config" }, { label: "导出通道", path: "/export_channel" }, { label: "运行历史", path: "/run_history" }, { label: "Schema校验", path: "/schema_check" }, { label: "内容缓存", path: "/content_cache" }]
</script>
