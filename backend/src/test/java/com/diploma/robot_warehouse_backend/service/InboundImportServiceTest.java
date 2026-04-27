package com.diploma.robot_warehouse_backend.service;

import com.diploma.robot_warehouse_backend.dto.InboundImportResult;
import com.diploma.robot_warehouse_backend.entity.Inbound;
import com.diploma.robot_warehouse_backend.entity.InboundLine;
import com.diploma.robot_warehouse_backend.entity.Product;
import com.diploma.robot_warehouse_backend.entity.Task;
import com.diploma.robot_warehouse_backend.enums.Status;
import com.diploma.robot_warehouse_backend.repository.InboundLineRepository;
import com.diploma.robot_warehouse_backend.repository.InboundRepository;
import com.diploma.robot_warehouse_backend.repository.ProductRepository;
import com.diploma.robot_warehouse_backend.repository.TaskRepository;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.junit.jupiter.api.io.TempDir;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.test.util.ReflectionTestUtils;

import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

@ExtendWith(MockitoExtension.class)
class InboundImportServiceTest {

    @Mock
    private InboundRepository inboundRepository;

    @Mock
    private ProductRepository productRepository;

    @Mock
    private TaskRepository taskRepository;

    @Mock
    private InboundLineRepository inboundLineRepository;

    @InjectMocks
    private InboundImportService inboundImportService;

    @TempDir
    Path tempDir;

    @Test
    @DisplayName("importInbound: должен создать inbound, строки и задачи, пропуская заголовок и пустые строки")
    void importInbound_shouldCreateInboundLinesAndTasks() throws Exception {
        Path file = tempDir.resolve("inbound.txt");
        Files.writeString(file, """
                sku;manufacturer;name;quantity
                SKU-1;MFG-1;Product One;2
                
                SKU-2;MFG-2;Product Two;1
                """);

        String externalRef = "EXT-001";

        Product existingProduct = product(10, "SKU-1", "MFG-1", "Product One");

        when(inboundRepository.existsByExternalRef(externalRef)).thenReturn(false);

        when(inboundRepository.save(any(Inbound.class))).thenAnswer(inv -> {
            Inbound inbound = inv.getArgument(0);
            setField(inbound, 123, "id", "inboundId");
            return inbound;
        });

        when(productRepository.findBySkuAndManufacturer("SKU-1", "MFG-1"))
                .thenReturn(Optional.of(existingProduct));
        when(productRepository.findBySkuAndManufacturer("SKU-2", "MFG-2"))
                .thenReturn(Optional.empty());

        when(productRepository.save(any(Product.class))).thenAnswer(inv -> {
            Product p = inv.getArgument(0);
            if (getField(p, "id", "productId") == null) {
                setField(p, 20, "id", "productId");
            }
            return p;
        });

        when(inboundLineRepository.save(any(InboundLine.class))).thenAnswer(inv -> inv.getArgument(0));
        when(taskRepository.saveAll(anyList())).thenAnswer(inv -> inv.getArgument(0));

        InboundImportResult result = inboundImportService.importInbound(file, externalRef);

        assertEquals(Integer.valueOf(123), result.getInboundId());
        assertEquals(Integer.valueOf(2), result.getLinesCount());
        assertEquals(Integer.valueOf(3), result.getTasksCreated());
        assertEquals("inbound.txt", result.getFileName());

        ArgumentCaptor<Inbound> inboundCaptor = ArgumentCaptor.forClass(Inbound.class);
        verify(inboundRepository).save(inboundCaptor.capture());

        Inbound savedInbound = inboundCaptor.getValue();
        assertEquals(externalRef, getField(savedInbound, "externalRef"));
        assertEquals("inbound.txt", getField(savedInbound, "fileName"));
        assertEquals(Status.NEW, getField(savedInbound, "status"));

        verify(productRepository, times(1))
                .save(any(Product.class));
        verify(inboundLineRepository, times(2))
                .save(any(InboundLine.class));

        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Task>> tasksCaptor = ArgumentCaptor.forClass((Class) List.class);
        verify(taskRepository, times(2)).saveAll(tasksCaptor.capture());

        List<List<Task>> allSavedTaskBatches = tasksCaptor.getAllValues();
        assertEquals(2, allSavedTaskBatches.size());
        assertEquals(2, allSavedTaskBatches.get(0).size());
        assertEquals(1, allSavedTaskBatches.get(1).size());
    }

    @Test
    @DisplayName("importInbound: если externalRef уже импортирован, должен выбросить исключение")
    void importInbound_shouldThrowWhenExternalRefAlreadyExists() throws Exception {
        Path file = tempDir.resolve("inbound.txt");
        Files.writeString(file, """
                sku;manufacturer;name;quantity
                SKU-1;MFG-1;Product One;1
                """);

        when(inboundRepository.existsByExternalRef("EXT-001")).thenReturn(true);

        IllegalArgumentException ex = assertThrows(
                IllegalArgumentException.class,
                () -> inboundImportService.importInbound(file, "EXT-001")
        );

        assertTrue(ex.getMessage().contains("Already imported"));

        verify(inboundRepository).existsByExternalRef("EXT-001");
        verifyNoMoreInteractions(productRepository, taskRepository, inboundLineRepository);
    }

    @Test
    @DisplayName("importInbound: если файл не существует, должен выбросить исключение")
    void importInbound_shouldThrowWhenFileDoesNotExist() {
        Path file = tempDir.resolve("missing.txt");

        IllegalArgumentException ex = assertThrows(
                IllegalArgumentException.class,
                () -> inboundImportService.importInbound(file, "EXT-001")
        );

        assertTrue(ex.getMessage().contains("File does not exist"));
        verifyNoInteractions(inboundRepository, productRepository, taskRepository, inboundLineRepository);
    }

    @Test
    @DisplayName("importInbound: если файл пустой, должен выбросить исключение")
    void importInbound_shouldThrowWhenFileIsEmpty() throws Exception {
        Path file = tempDir.resolve("empty.txt");
        Files.writeString(file, "");

        IllegalArgumentException ex = assertThrows(
                IllegalArgumentException.class,
                () -> inboundImportService.importInbound(file, "EXT-001")
        );

        assertTrue(ex.getMessage().contains("File is empty"));
        verifyNoInteractions(inboundRepository, productRepository, taskRepository, inboundLineRepository);
    }

    // helpers

    private Product product(Integer id, String sku, String manufacturer, String name) {
        Product product = new Product();
        setField(product, id, "id", "productId");
        setField(product, sku, "sku");
        setField(product, manufacturer, "manufacturer");
        setField(product, name, "name");
        return product;
    }

    @SuppressWarnings("unchecked")
    private static <T> T getField(Object target, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                return (T) ReflectionTestUtils.getField(target, fieldName);
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }

    private static void setField(Object target, Object value, String... fieldNames) {
        for (String fieldName : fieldNames) {
            try {
                ReflectionTestUtils.setField(target, fieldName, value);
                return;
            } catch (IllegalArgumentException ignored) {
            }
        }
        throw new IllegalArgumentException("Field not found in " + target.getClass().getSimpleName());
    }
}