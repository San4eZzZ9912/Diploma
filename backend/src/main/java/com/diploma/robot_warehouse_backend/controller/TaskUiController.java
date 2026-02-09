package com.diploma.robot_warehouse_backend.controller;

import com.diploma.robot_warehouse_backend.service.TasksUiService;
import lombok.Getter;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;

@Controller
@RequestMapping("/tasks")
public class TaskUiController {
    private final TasksUiService tasksUiService;

    public TaskUiController(TasksUiService tasksUiService) {
        this.tasksUiService = tasksUiService;
    }

    @GetMapping
    public String list(Model model) {
        model.addAttribute("newTasks", tasksUiService.getNewTasks());
        model.addAttribute("inProgressTasks", tasksUiService.getInProgressTasks());
        model.addAttribute("recentTasks", tasksUiService.getRecentDoneOrError());
        return "/tasks/list";
    }
}
