package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.OutboundCreateRequest;
import com.diploma.robot_warehouse_backend.dto.OutboundCreateResult;
import com.diploma.robot_warehouse_backend.dto.OutboundDetailsView;
import com.diploma.robot_warehouse_backend.dto.OutboundItemRequest;
import com.diploma.robot_warehouse_backend.entity.Outbound;
import com.diploma.robot_warehouse_backend.entity.OutboundLine;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.OutboundLineRepository;
import com.diploma.robot_warehouse_backend.repository.OutboundRepository;
import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.repository.SlotStateRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import java.util.concurrent.atomic.AtomicInteger;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class OutboundServiceTest {

    @Mock
    private OutboundRepository outboundRepository;

    @Mock
    private OutboundLineRepository outboundLineRepository;

    @Mock
    private ProductRepository productRepository;

    @Mock
    private TaskRepository taskRepository;

    @Mock
    private SlotStateRepository slotStateRepository;

    private OutboundService outboundService;

    @BeforeEach
    void setUp() {
        outboundService = new OutboundService(
                outboundRepository,
                outboundLineRepository,
                productRepository,
                taskRepository,
                slotStateRepository
        );
    }

    @Test
    void createOutbound_shouldCreateOutboundLinesAndTasks() {
        Product product1 = product(1, "SKU-1", "Bosch", "Дрель");
        Product product2 = product(2, "SKU-2", "Makita", "Шуруповерт");

        OutboundCreateRequest request = request(
                "OUT-001",
                item(1, 2),
                item(2, 1)
        );

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);
        when(productRepository.findById(1)).thenReturn(Optional.of(product1));
        when(productRepository.findById(2)).thenReturn(Optional.of(product2));
        when(slotStateRepository.countAvailableStorageByProductId(1)).thenReturn(5);
        when(slotStateRepository.countAvailableStorageByProductId(2)).thenReturn(3);

        when(outboundRepository.save(any(Outbound.class))).thenAnswer(invocation -> {
            Outbound outbound = invocation.getArgument(0);
            ReflectionTestUtils.setField(outbound, "id", 100);
            return outbound;
        });

        AtomicInteger outboundLineId = new AtomicInteger(1);
        when(outboundLineRepository.save(any(OutboundLine.class))).thenAnswer(invocation -> {
            OutboundLine line = invocation.getArgument(0);
            ReflectionTestUtils.setField(line, "id", outboundLineId.getAndIncrement());
            return line;
        });

        OutboundCreateResult result = outboundService.createOutbound(request);

        assertThat(result.getOutboundId()).isEqualTo(100);
        assertThat(result.getLinesCreated()).isEqualTo(2);
        assertThat(result.getTasksCreated()).isEqualTo(3);

        ArgumentCaptor<Outbound> outboundCaptor = ArgumentCaptor.forClass(Outbound.class);
        verify(outboundRepository).save(outboundCaptor.capture());

        Outbound savedOutbound = outboundCaptor.getValue();
        assertThat(savedOutbound.getExternalRef()).isEqualTo("OUT-001");
        assertThat(savedOutbound.getStatus()).isEqualTo(Status.NEW);

        ArgumentCaptor<OutboundLine> lineCaptor = ArgumentCaptor.forClass(OutboundLine.class);
        verify(outboundLineRepository, times(2)).save(lineCaptor.capture());

        List<OutboundLine> savedLines = lineCaptor.getAllValues();

        assertThat(savedLines).hasSize(2);

        assertThat(savedLines.get(0).getOutbound()).isSameAs(savedOutbound);
        assertThat(savedLines.get(0).getProduct()).isSameAs(product1);
        assertThat(savedLines.get(0).getQuantity()).isEqualTo(2);

        assertThat(savedLines.get(1).getOutbound()).isSameAs(savedOutbound);
        assertThat(savedLines.get(1).getProduct()).isSameAs(product2);
        assertThat(savedLines.get(1).getQuantity()).isEqualTo(1);

        ArgumentCaptor<Iterable<Task>> tasksCaptor = ArgumentCaptor.forClass(Iterable.class);
        verify(taskRepository).saveAll(tasksCaptor.capture());

        List<Task> savedTasks = toList(tasksCaptor.getValue());

        assertThat(savedTasks).hasSize(3);

        assertThat(savedTasks)
                .allSatisfy(task -> assertThat(task.getStatus()).isEqualTo(Status.NEW));

        assertThat(savedTasks)
                .extracting(Task::getProduct)
                .containsExactly(product1, product1, product2);
    }

    @Test
    void createOutbound_shouldMergeSameProductIntoOneLine() {
        Product product = product(1, "SKU-1", "Bosch", "Дрель");

        OutboundCreateRequest request = request(
                "OUT-002",
                item(1, 1),
                item(1, 2),
                item(1, 3)
        );

        when(outboundRepository.existsByExternalRef("OUT-002")).thenReturn(false);
        when(productRepository.findById(1)).thenReturn(Optional.of(product));
        when(slotStateRepository.countAvailableStorageByProductId(1)).thenReturn(10);

        when(outboundRepository.save(any(Outbound.class))).thenAnswer(invocation -> {
            Outbound outbound = invocation.getArgument(0);
            ReflectionTestUtils.setField(outbound, "id", 200);
            return outbound;
        });

        when(outboundLineRepository.save(any(OutboundLine.class))).thenAnswer(invocation -> {
            OutboundLine line = invocation.getArgument(0);
            ReflectionTestUtils.setField(line, "id", 1);
            return line;
        });

        OutboundCreateResult result = outboundService.createOutbound(request);

        assertThat(result.getOutboundId()).isEqualTo(200);
        assertThat(result.getLinesCreated()).isEqualTo(1);
        assertThat(result.getTasksCreated()).isEqualTo(6);

        ArgumentCaptor<OutboundLine> lineCaptor = ArgumentCaptor.forClass(OutboundLine.class);
        verify(outboundLineRepository).save(lineCaptor.capture());

        OutboundLine savedLine = lineCaptor.getValue();

        assertThat(savedLine.getProduct()).isSameAs(product);
        assertThat(savedLine.getQuantity()).isEqualTo(6);

        ArgumentCaptor<Iterable<Task>> tasksCaptor = ArgumentCaptor.forClass(Iterable.class);
        verify(taskRepository).saveAll(tasksCaptor.capture());

        List<Task> savedTasks = toList(tasksCaptor.getValue());

        assertThat(savedTasks).hasSize(6);
        assertThat(savedTasks)
                .allSatisfy(task -> assertThat(task.getProduct()).isSameAs(product));
    }

    @Test
    void createOutbound_shouldThrowException_whenRequestIsNull() {
        assertThatThrownBy(() -> outboundService.createOutbound(null))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Request is required");

        verifyNoInteractions(outboundRepository);
        verifyNoInteractions(outboundLineRepository);
        verifyNoInteractions(productRepository);
        verifyNoInteractions(taskRepository);
        verifyNoInteractions(slotStateRepository);
    }

    @Test
    void createOutbound_shouldThrowException_whenExternalRefIsBlank() {
        OutboundCreateRequest request = request(
                "   ",
                item(1, 1)
        );

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("External ref is required");

        verify(outboundRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenExternalRefAlreadyExists() {
        OutboundCreateRequest request = request(
                "OUT-001",
                item(1, 1)
        );

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(true);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("External ref already exists");

        verify(outboundRepository, never()).save(any());
        verify(outboundLineRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenItemsAreEmpty() {
        OutboundCreateRequest request = new OutboundCreateRequest();
        request.setExternalRef("OUT-001");
        request.setItems(List.of());

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("At least one item is required");

        verify(outboundRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenItemIsNull() {
        OutboundCreateRequest request = new OutboundCreateRequest();
        request.setExternalRef("OUT-001");

        List<OutboundItemRequest> items = new ArrayList<>();
        items.add(null);

        request.setItems(items);

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Item is null");

        verify(outboundRepository, never()).save(any());
        verify(outboundLineRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenProductIdIsNull() {
        OutboundItemRequest item = new OutboundItemRequest();
        item.setProductId(null);
        item.setQuantity(1);

        OutboundCreateRequest request = new OutboundCreateRequest();
        request.setExternalRef("OUT-001");
        request.setItems(List.of(item));

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Product id is required");

        verify(outboundRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenQuantityIsZeroOrNegative() {
        OutboundCreateRequest request = request(
                "OUT-001",
                item(1, 0)
        );

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Quantity must be > 0");

        verify(outboundRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenProductNotFound() {
        OutboundCreateRequest request = request(
                "OUT-001",
                item(999, 1)
        );

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);
        when(productRepository.findById(999)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Product not found: 999");

        verify(outboundRepository, never()).save(any());
        verify(outboundLineRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void createOutbound_shouldThrowException_whenNotEnoughProductInStorage() {
        Product product = product(1, "SKU-1", "Bosch", "Дрель");

        OutboundCreateRequest request = request(
                "OUT-001",
                item(1, 5)
        );

        when(outboundRepository.existsByExternalRef("OUT-001")).thenReturn(false);
        when(productRepository.findById(1)).thenReturn(Optional.of(product));
        when(slotStateRepository.countAvailableStorageByProductId(1)).thenReturn(2);

        assertThatThrownBy(() -> outboundService.createOutbound(request))
                .isInstanceOf(IllegalStateException.class)
                .hasMessageContaining("Недостаточно товара на складе")
                .hasMessageContaining("Запрошено=5")
                .hasMessageContaining("доступно=2");

        verify(outboundRepository, never()).save(any());
        verify(outboundLineRepository, never()).save(any());
        verify(taskRepository, never()).saveAll(any());
    }

    @Test
    void getOutboundDetails_shouldReturnOutboundDetailsView() {
        Product product1 = product(1, "SKU-1", "Bosch", "Дрель");
        Product product2 = product(2, "SKU-2", "Makita", "Шуруповерт");

        Outbound outbound = new Outbound("OUT-001", Status.NEW);
        ReflectionTestUtils.setField(outbound, "id", 100);

        OutboundLine line1 = new OutboundLine(outbound, product1, 2);
        ReflectionTestUtils.setField(line1, "id", 10);

        OutboundLine line2 = new OutboundLine(outbound, product2, 1);
        ReflectionTestUtils.setField(line2, "id", 11);

        Task task1 = new Task(Status.NEW, line1, product1);
        ReflectionTestUtils.setField(task1, "id", 1000);

        Task task2 = new Task(Status.IN_PROGRESS, line1, product1);
        ReflectionTestUtils.setField(task2, "id", 1001);

        Task task3 = new Task(Status.NEW, line2, product2);
        ReflectionTestUtils.setField(task3, "id", 1002);

        when(outboundRepository.findById(100)).thenReturn(Optional.of(outbound));
        when(outboundLineRepository.findByOutboundIdWithProduct(100))
                .thenReturn(List.of(line1, line2));
        when(taskRepository.findByOutboundIdWithProduct(100))
                .thenReturn(List.of(task1, task2, task3));

        OutboundDetailsView view = outboundService.getOutboundDetails(100);

        assertThat(view.getOutboundId()).isEqualTo(100);
        assertThat(view.getExternalRef()).isEqualTo("OUT-001");
        assertThat(view.getStatus()).isEqualTo("NEW");

        assertThat(view.getLines()).hasSize(2);

        assertThat(view.getLines().get(0).getLineId()).isEqualTo(10);
        assertThat(view.getLines().get(0).getProductName()).isEqualTo("Дрель");
        assertThat(view.getLines().get(0).getSku()).isEqualTo("SKU-1");
        assertThat(view.getLines().get(0).getManufacturer()).isEqualTo("Bosch");
        assertThat(view.getLines().get(0).getQuantity()).isEqualTo(2);

        assertThat(view.getLines().get(1).getLineId()).isEqualTo(11);
        assertThat(view.getLines().get(1).getProductName()).isEqualTo("Шуруповерт");
        assertThat(view.getLines().get(1).getSku()).isEqualTo("SKU-2");
        assertThat(view.getLines().get(1).getManufacturer()).isEqualTo("Makita");
        assertThat(view.getLines().get(1).getQuantity()).isEqualTo(1);

        assertThat(view.getTasks()).hasSize(3);

        assertThat(view.getTasks().get(0).getTaskId()).isEqualTo(1000);
        assertThat(view.getTasks().get(0).getProductName()).isEqualTo("Дрель");
        assertThat(view.getTasks().get(0).getSku()).isEqualTo("SKU-1");
        assertThat(view.getTasks().get(0).getManufacturer()).isEqualTo("Bosch");
        assertThat(view.getTasks().get(0).getStatus()).isEqualTo(Status.NEW);

        assertThat(view.getTasks().get(1).getTaskId()).isEqualTo(1001);
        assertThat(view.getTasks().get(1).getStatus()).isEqualTo(Status.IN_PROGRESS);

        assertThat(view.getTasks().get(2).getTaskId()).isEqualTo(1002);
        assertThat(view.getTasks().get(2).getProductName()).isEqualTo("Шуруповерт");
        assertThat(view.getTasks().get(2).getStatus()).isEqualTo(Status.NEW);
    }

    @Test
    void getOutboundDetails_shouldThrowException_whenOutboundNotFound() {
        when(outboundRepository.findById(404)).thenReturn(Optional.empty());

        assertThatThrownBy(() -> outboundService.getOutboundDetails(404))
                .isInstanceOf(IllegalArgumentException.class)
                .hasMessage("Outbound not found: 404");

        verify(outboundLineRepository, never()).findByOutboundIdWithProduct(any());
        verify(taskRepository, never()).findByOutboundIdWithProduct(any());
    }

    private OutboundCreateRequest request(String externalRef, OutboundItemRequest... items) {
        OutboundCreateRequest request = new OutboundCreateRequest();
        request.setExternalRef(externalRef);
        request.setItems(List.of(items));
        return request;
    }

    private OutboundItemRequest item(Integer productId, Integer quantity) {
        OutboundItemRequest item = new OutboundItemRequest();
        item.setProductId(productId);
        item.setQuantity(quantity);
        return item;
    }

    private Product product(Integer id, String sku, String manufacturer, String name) {
        Product product = new Product();

        ReflectionTestUtils.setField(product, "id", id);
        ReflectionTestUtils.setField(product, "sku", sku);
        ReflectionTestUtils.setField(product, "manufacturer", manufacturer);
        ReflectionTestUtils.setField(product, "name", name);

        return product;
    }

    private List<Task> toList(Iterable<Task> iterable) {
        List<Task> result = new ArrayList<>();
        iterable.forEach(result::add);
        return result;
    }
}