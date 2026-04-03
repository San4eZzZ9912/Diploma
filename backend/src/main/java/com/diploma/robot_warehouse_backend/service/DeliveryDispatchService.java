package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.DeliveryTaskResponse;
import com.diploma.robot_warehouse_backend.entity.Outbound;
import com.diploma.robot_warehouse_backend.entity.Shelf;
import com.diploma.robot_warehouse_backend.entity.ShelfSlot;
import com.diploma.robot_warehouse_backend.entity.SlotState;
import com.diploma.robot_warehouse_backend.entity.Task;
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
import java.util.List;
import java.util.Optional;

@Service
public class DeliveryDispatchService {
    private final TaskRepository taskRepository;
    private final SlotStateRepository slotStateRepository;
    private final ShelfRepository shelfRepository;
    private final DeliveryTaskMapper deliveryTaskMapper;

    public DeliveryDispatchService(TaskRepository taskRepository,
                                   SlotStateRepository slotStateRepository,
                                   ShelfRepository shelfRepository,
                                   DeliveryTaskMapper deliveryTaskMapper) {
        this.taskRepository = taskRepository;
        this.slotStateRepository = slotStateRepository;
        this.shelfRepository = shelfRepository;
        this.deliveryTaskMapper = deliveryTaskMapper;
    }

    @Transactional
    public Optional<DeliveryTaskResponse> getNextDeliveryTask(String robotId) {
        Task task = taskRepository.findNextNewDeliveryForUpdate().orElse(null);
        if (task == null) {
            return Optional.empty();
        }

        if (task.getProduct() == null) {
            throw new IllegalStateException("DELIVERY task has no product: taskId=" + task.getId());
        }

        SlotState sourceState = slotStateRepository
                .findOldestOccupiedStorageByProductIdForUpdate(task.getProduct().getId())
                .orElse(null);

        if (sourceState == null) {
            return Optional.empty();
        }

        SlotState targetState = slotStateRepository
                .findFirstFreeDeliveryUpperForUpdate()
                .orElse(null);

        if (targetState == null) {
            return Optional.empty();
        }

        ShelfSlot sourceSlot = sourceState.getSlot();
        ShelfSlot targetSlot = targetState.getSlot();

        Shelf deliveryShelf = shelfRepository.findFirstByRole(Role.DELIVERY)
                .orElseThrow(() -> new IllegalArgumentException("DELIVERY shelf not found"));

        LocalDateTime now = LocalDateTime.now();

        sourceState.setReserved(true);
        sourceState.setReservedTaskId(task.getId());
        sourceState.setUpdatedAt(now);

        targetState.setReserved(true);
        targetState.setReservedTaskId(task.getId());
        targetState.setUpdatedAt(now);

        task.setStatus(Status.IN_PROGRESS);
        task.setRobotId(robotId);
        task.setSourceSlot(sourceSlot);
        task.setTargetSlot(targetSlot);
        task.setUpdatedAt(now);

        slotStateRepository.save(sourceState);
        slotStateRepository.save(targetState);
        taskRepository.save(task);

        DeliveryTaskResponse response = deliveryTaskMapper.toResponse(task, deliveryShelf);
        return Optional.of(response);
    }

    @Transactional
    public void completeDeliveryTask(Integer taskId, String robotId, boolean success) {
        Task task = taskRepository.findById(taskId)
                .orElseThrow(() -> new IllegalArgumentException("Task not found: " + taskId));

        if (task.getType() != Type.DELIVERY) {
            throw new IllegalStateException("Task is not DELIVERY: " + taskId + ", type=" + task.getType());
        }

        if (!Status.IN_PROGRESS.equals(task.getStatus())) {
            throw new IllegalStateException("Task is not IN_PROGRESS: " + taskId + ", status=" + task.getStatus());
        }

        if (task.getRobotId() != null && !task.getRobotId().equals(robotId)) {
            throw new IllegalStateException(
                    "Task is owned by another robot: taskRobot=" + task.getRobotId() + ", robotId=" + robotId
            );
        }

        ShelfSlot sourceSlot = task.getSourceSlot();
        if (sourceSlot == null) {
            throw new IllegalStateException("DELIVERY task has no sourceSlot: taskId=" + taskId);
        }

        ShelfSlot targetSlot = task.getTargetSlot();
        if (targetSlot == null) {
            throw new IllegalStateException("DELIVERY task has no targetSlot: taskId=" + taskId);
        }

        SlotState sourceState = slotStateRepository.findById(sourceSlot.getId())
                .orElseThrow(() -> new IllegalArgumentException("slot_state not found for sourceSlotId=" + sourceSlot.getId()));

        SlotState targetState = slotStateRepository.findById(targetSlot.getId())
                .orElseThrow(() -> new IllegalArgumentException("slot_state not found for targetSlotId=" + targetSlot.getId()));

        LocalDateTime now = LocalDateTime.now();

        if (success) {
            // 1. STORAGE: товар забрали, слот освобождаем
            sourceState.setReserved(false);
            sourceState.setReservedTaskId(null);
            sourceState.setOccupied(false);
            sourceState.setProduct(null);
            sourceState.setStoredAt(null);
            sourceState.setCubeQr(null);
            sourceState.setUpdatedAt(now);
            sourceState.setRobotId(robotId);

            // 2. DELIVERY: товар привезён пользователю, слот теперь занят товаром
            targetState.setReserved(false);
            targetState.setReservedTaskId(null);
            targetState.setOccupied(true);
            targetState.setProduct(task.getProduct());
            targetState.setStoredAt(now);
            targetState.setUpdatedAt(now);
            targetState.setRobotId(robotId);

            // если у тебя в DELIVERY тоже используется cubeQr — можно записать
            // targetState.setCubeQr(buildCubeQr(task.getProduct().getSku(), task.getProduct().getManufacturer()));

            // 3. Задача ещё НЕ завершена полностью: пользователь товар ещё не забрал
            task.setStatus(Status.WAITING_PICKUP);
        } else {
            // если робот не довёз товар:
            // STORAGE остаётся занятым товаром, просто снимаем резерв
            sourceState.setReserved(false);
            sourceState.setReservedTaskId(null);
            sourceState.setUpdatedAt(now);
            sourceState.setRobotId(robotId);

            // DELIVERY target-slot освобождаем от резерва,
            // потому что товар туда не был доставлен
            targetState.setReserved(false);
            targetState.setReservedTaskId(null);
            targetState.setUpdatedAt(now);
            targetState.setRobotId(robotId);

            task.setStatus(Status.ERROR);
        }

        task.setUpdatedAt(now);

        slotStateRepository.save(sourceState);
        slotStateRepository.save(targetState);
        taskRepository.save(task);
    }

    /**
     * Пользователь нажал кнопку, что забрал текущую партию товаров с полки DELIVERY.
     * Освобождаем delivery-слоты и переводим задачи в DONE.
     */
    @Transactional
    public void confirmPickup(Integer outboundId) {
        List<Task> waitingTasks = taskRepository.findByOutboundLine_Outbound_IdAndStatus(outboundId, Status.WAITING_PICKUP);

        if (waitingTasks.isEmpty()) {
            throw new IllegalStateException("No WAITING_PICKUP tasks for outboundId=" + outboundId);
        }

        LocalDateTime now = LocalDateTime.now();

        for (Task task : waitingTasks) {
            ShelfSlot targetSlot = task.getTargetSlot();
            if (targetSlot == null) {
                throw new IllegalStateException("Task has no targetSlot: taskId=" + task.getId());
            }

            SlotState targetState = slotStateRepository.findById(targetSlot.getId())
                    .orElseThrow(() -> new IllegalArgumentException("slot_state not found for targetSlotId=" + targetSlot.getId()));

            // очищаем полку DELIVERY после того, как пользователь забрал товар
            targetState.setReserved(false);
            targetState.setReservedTaskId(null);
            targetState.setOccupied(false);
            targetState.setProduct(null);
            targetState.setStoredAt(null);
            targetState.setCubeQr(null);
            targetState.setUpdatedAt(now);

            task.setStatus(Status.DONE);
            task.setUpdatedAt(now);

            slotStateRepository.save(targetState);
            taskRepository.save(task);
        }

        // если все задачи outbound завершены — можно закрыть сам outbound
        Outbound outbound = waitingTasks.get(0).getOutboundLine().getOutbound();

        boolean hasUnfinished = taskRepository.existsByOutboundLine_Outbound_IdAndStatusIn(
                outboundId,
                List.of(Status.NEW, Status.IN_PROGRESS, Status.WAITING_PICKUP)
        );

        if (!hasUnfinished) {
            outbound.setStatus(Status.DONE);
        } else {
            outbound.setStatus(Status.IN_PROGRESS);
        }
    }

    private String buildCubeQr(String sku, String manufacturer) {
        if (sku == null || manufacturer == null) {
            return null;
        }
        return sku.trim() + "/" + manufacturer.trim();
    }
}