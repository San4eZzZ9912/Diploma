package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.TaskUiRow;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import java.util.List;

@Service
public class TasksUiService {
    private final TaskRepository taskRepository;

    public TasksUiService(TaskRepository taskRepository) {
        this.taskRepository = taskRepository;
    }

    @Transactional(readOnly = true)
    public List<TaskUiRow> getNewTasks() {
        return taskRepository.findTop50ByStatusOrderByCreatedAtDesc(Status.NEW).stream().map(this::toRow).toList();
    }

    @Transactional(readOnly = true)
    public List<TaskUiRow> getInProgressTasks() {
        return taskRepository.findTop50ByStatusOrderByUpdatedAtDesc(Status.IN_PROGRESS).stream().map(this::toRow).toList();
    }

    @Transactional(readOnly = true)
    public List<TaskUiRow> getRecentDoneOrError() {
        return taskRepository.findTop50ByStatusInOrderByUpdatedAtDesc(List.of(Status.DONE, Status.ERROR)).stream().map(this::toRow).toList();
    }

    private TaskUiRow toRow(Task t) {
        return new TaskUiRow(
                t.getId(),
                t.getStatus(),
                t.getRobotId(),
                t.getProduct() != null ? t.getProduct().getSku() : null,
                t.getProduct() != null ? t.getProduct().getManufacturer() : null,
                t.getTargetShelfCode(),
                t.getTargetSide(),
                t.getTargetLevel(),
                t.getCreatedAt(),
                t.getUpdatedAt()
        );
    }
}
