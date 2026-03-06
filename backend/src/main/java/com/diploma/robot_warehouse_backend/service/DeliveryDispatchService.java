package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.DeliveryTaskResponse;
import com.diploma.robot_warehouse_backend.entity.*;
import com.diploma.robot_warehouse_backend.enums.Role;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.enums.Type;
import com.diploma.robot_warehouse_backend.mapper.DeliveryTaskMapper;
import com.diploma.robot_warehouse_backend.repository.ShelfRepository;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.Optional;

@Service
public class DeliveryDispatchService {
    private final TaskRepository taskRepository;
    private final SlotStateRepository slotStateRepository;
    private final ShelfRepository shelfRepository;
    private final DeliveryTaskMapper deliveryTaskMapper;

    public DeliveryDispatchService(TaskRepository taskRepository, SlotStateRepository slotStateRepository, ShelfRepository shelfRepository, DeliveryTaskMapper deliveryTaskMapper) {
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
        this.shelfRepository = shelfRepository;
        this.deliveryTaskMapper = deliveryTaskMapper;
    }

    @Transactional
    public Optional<DeliveryTaskResponse> getNextDeliveryTask(String robotId) {
        Task task = taskRepository.findNextNewDeliveryForUpdate().orElse(null);
        if (task == null) return Optional.empty();

        Product product = task.getProduct();

        SlotState occupied = slotStateRepository
                .findOldestOccupiedStorageByProductIdForUpdate(product.getId())
                .orElse(null);

        if (occupied == null) {
            return Optional.empty();
        }

        ShelfSlot sourceSlot = occupied.getSlot();
        Shelf sourceShelf = sourceSlot.getShelf();

        SlotState deliveryFree = slotStateRepository.findFirstFreeDeliveryUpperForUpdate().orElse(null);

        if (deliveryFree == null) {
            return Optional.empty();
        }

        Shelf deliveryShelf = shelfRepository.findFirstByRole(Role.DELIVERY).orElseThrow(() -> new IllegalArgumentException("DELIVERY shelf not found"));
        ShelfSlot targetSlot = deliveryFree.getSlot();

        occupied.setReserved(true);
        occupied.setReservedTaskId(task.getId());
        occupied.setUpdatedAt(LocalDateTime.now());

        deliveryFree.setReserved(true);
        deliveryFree.setReservedTaskId(task.getId());
        deliveryFree.setUpdatedAt(LocalDateTime.now());

        task.setStatus(Status.IN_PROGRESS);
        task.setRobotId(robotId);
        task.setSourceSlot(sourceSlot);
        task.setTargetSlot(targetSlot);
        task.setUpdatedAt(LocalDateTime.now());

        slotStateRepository.save(occupied);
        slotStateRepository.save(deliveryFree);
        taskRepository.save(task);

        DeliveryTaskResponse deliveryTaskResponse = deliveryTaskMapper.toResponse(task, deliveryShelf);

        return Optional.of(deliveryTaskResponse);
    }

    @Transactional
    public void completeDeliveryTask(Integer taskId, String robotId, boolean success) {
        Task task = taskRepository.findById(taskId).orElseThrow(() -> new IllegalArgumentException("Task not found: " + taskId));

        if (task.getType() != Type.DELIVERY) {
            throw new IllegalStateException("Task is not DELIVERY: " + taskId + ", type=" + task.getType());
        }
        if (!Status.IN_PROGRESS.equals(task.getStatus())) {
            throw new IllegalStateException("Task is not IN_PROGRESS: " + taskId + ", status=" + task.getStatus());
        }
        if (task.getRobotId() != null && !task.getRobotId().equals(robotId)) {
            throw new IllegalStateException("Task is owned by another robot: taskRobot=" + task.getRobotId() + ", robotId=" + robotId);
        }

        ShelfSlot sourceSlot = task.getSourceSlot();
        if (sourceSlot == null) {
            throw new IllegalStateException("DELIVERY task has no sourceSlot: taskId=" + taskId);
        }

        SlotState sourceState = slotStateRepository.findById(sourceSlot.getId()).orElseThrow(
                () -> new IllegalArgumentException("slot_state not found for slotId=" + sourceSlot.getId())
        );

        sourceState.setReserved(false);
        sourceState.setReservedTaskId(null);
        sourceState.setUpdatedAt(LocalDateTime.now());
        sourceState.setRobotId(robotId);

        if (success) {
            sourceState.setOccupied(false);
            sourceState.setProduct(null);
            sourceState.setStoredAt(null);
            sourceState.setCubeQr(null);
            task.setStatus(Status.DONE);
        } else {
            task.setStatus(Status.ERROR);
        }

        task.setUpdatedAt(LocalDateTime.now());

        slotStateRepository.save(sourceState);
        taskRepository.save(task);
    }

    private String buildCubeQr(String sku, String manufacturer) {
        if (sku == null || manufacturer == null) return null;
        return sku.trim() + "/" + manufacturer.trim();
    }
}
