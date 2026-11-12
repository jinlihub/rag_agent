<script setup lang="ts">
/** Kael Mind 品牌标志：圆角方徽 + K 字连节点 + 思绪火花（渐变随实例生成独立 id，可同页多渲） */
withDefaults(defineProps<{ size?: number }>(), { size: 30 })

const uid = `km-g-${Math.random().toString(36).slice(2, 8)}`
</script>

<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 48 48"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    aria-hidden="true"
  >
    <defs>
      <linearGradient :id="uid" x1="7" y1="5" x2="41" y2="43" gradientUnits="userSpaceOnUse">
        <stop stop-color="#6AA8FF" />
        <stop offset="1" stop-color="#3D6EF7" />
      </linearGradient>
    </defs>

    <!-- 底徽：圆角方 + 渐变 + 内圈高光 -->
    <rect x="2" y="2" width="44" height="44" rx="13" :fill="`url(#${uid})`" />
    <rect
      x="2.75"
      y="2.75"
      width="42.5"
      height="42.5"
      rx="12.25"
      stroke="#FFFFFF"
      stroke-opacity="0.25"
      stroke-width="1.5"
    />

    <!-- K：竖干 + 两斜笔，斜笔末端收成节点（知识 → 连线成"心"） -->
    <path d="M17.2 13.5v21" stroke="#fff" stroke-width="3.6" stroke-linecap="round" />
    <path d="M18.2 24.2 29.8 14.3" stroke="#fff" stroke-width="3.6" stroke-linecap="round" />
    <path d="M18.2 23.8 29.8 33.7" stroke="#fff" stroke-width="3.6" stroke-linecap="round" />
    <circle cx="31.9" cy="13" r="2.5" fill="#fff" />
    <circle cx="31.9" cy="35" r="2.5" fill="#fff" />

    <!-- 思绪火花：细线牵出一颗游离节点，落在右上角留白处 -->
    <path
      d="m34.1 11.6 3.3-2.4"
      stroke="#fff"
      stroke-opacity="0.55"
      stroke-width="1.4"
      stroke-linecap="round"
    />
    <circle cx="39.3" cy="7.9" r="2.1" fill="#fff" fill-opacity="0.92" />
  </svg>
</template>
