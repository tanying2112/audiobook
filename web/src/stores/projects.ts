import { defineStore } from 'pinia'
import { ref } from 'vue'
import type { Project } from '../types'
import * as api from '../api'

export const useProjectStore = defineStore('projects', () => {
  const projects = ref<Project[]>([])
  const currentProject = ref<Project | null>(null)
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function loadProjects() {
    loading.value = true
    error.value = null
    try {
      projects.value = await api.fetchProjects()
    } catch (e: any) {
      error.value = e.message || 'Failed to fetch projects'
    } finally {
      loading.value = false
    }
  }

  async function loadProject(id: number) {
    loading.value = true
    error.value = null
    try {
      currentProject.value = await api.fetchProject(id)
    } catch (e: any) {
      error.value = e.message || 'Failed to fetch project'
    } finally {
      loading.value = false
    }
  }

  async function addProject(payload: Partial<Project>) {
    const project = await api.createProject(payload)
    projects.value.push(project)
    return project
  }

  async function editProject(id: number, payload: Partial<Project>) {
    const project = await api.updateProject(id, payload)
    const idx = projects.value.findIndex((p) => p.id === id)
    if (idx !== -1) projects.value[idx] = project
    if (currentProject.value?.id === id) currentProject.value = project
    return project
  }

  async function removeProject(id: number) {
    await api.deleteProject(id)
    projects.value = projects.value.filter((p) => p.id !== id)
    if (currentProject.value?.id === id) currentProject.value = null
  }

  return {
    projects, currentProject, loading, error,
    loadProjects, loadProject, addProject, editProject, removeProject,
  }
})
